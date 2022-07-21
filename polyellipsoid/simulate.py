from cmeutils.geometry import moit

import hoomd
import numpy as np


class Simulation:
    """Simulation initialization class.

    Parameters
    ----------
    system : polyellipsoid.system.System, required
        System containing initial snapshot
    epsilon : float, required
        Energy value for Gay-Berne pair potential
    lperp : float, required
        Perpendicular length for Gay-Berne pair potential
    lpar : float, required
        Parallel length for Gay-Berne pair potential
    bond_k : float, required
        Spring constant for hoomd.md.bond.Harmonic force
    r_cut : float, required
        Cutoff radius for potentials (in simulation distance units)
    tau : float, optional, default 0.1
        Thermostat coupling period (in simulation time units)
    dt : float, optional, default 0.001
        Size of simulation timestep (in simulation time units)
    seed : int, optional, default 21
        Seed passed to integrator when randomizing velocities.
    gsd_write : int, default 1e4
        Period to write simulation snapshots to gsd file.
    log_write : int, default 1e3
        Period to write simulation data to the log file.

    Methods
    -------
    shrink : Runs a Hoomd simulation
        Run a shrink simulation to reduce simulation volume to match
        the target box set by system.target_box
    quench : Runs a Hoomd simulation
        Run a simulation at a single temperature in NVT
    anneal : Runs a Hoomd simulation
        Define a schedule of temperature and steps to follow over the
        course of the simulation. Can be used in NVT or NPT at a single
        pressure.

    """
    def __init__(
            self,
            system,
            epsilon,
            lperp,
            lpar,
            bond_k,
            r_cut,
            tau=0.1,
            dt=0.001,
            seed=21,
            gsd_write=1e4,
            log_write=1e3,
    ):
        self.system = system
        self.snapshot = system.snapshot
        self.tau = tau
        self.gsd_write = gsd_write
        self.log_write = log_write
        self.ran_shrink = False
        self.log_quantities = [
            "kinetic_temperature",
            "potential_energy",
            "kinetic_energy",
            "volume",
            "pressure",
            "pressure_tensor"
        ]
        # Set up sim object
        self.sim = hoomd.Simulation(
                device=hoomd.device.auto_select(), seed=seed
        )
        self.sim.create_state_from_snapshot(self.snapshot)

        # Set up forces, GB pair and harmonic bond:
        nl = hoomd.md.nlist.Cell(buffer=0.40)
        gb = hoomd.md.pair.aniso.GayBerne(nlist=nl, default_r_cut=r_cut)
        gb.params[('R', 'R')] = dict(epsilon=epsilon, lperp=lperp, lpar=lpar)
        zero_pairs = [
                ('CT','CT'), ('CH','CT'), ('CH','CH'), ('CT','R'), ('CH','R')
        ]
        for pair in zero_pairs:
            gb.params[pair] = dict(epsilon=0.0, lperp=0.0, lpar=0.0)
        
        # Set up harmonic bond force
        harmonic = hoomd.md.bond.Harmonic()
        harmonic.params["CT-CH"] = dict(k=bond_k, r0=self.system.bond_length)
        harmonic.params["CH-CT"] = dict(k=bond_k, r0=self.system.bond_length)

        # Set up rigid object for Hoomd
        # Find the first 2 non-rigid particles (i.e. constiuent particles)
        inds = [self.system.n_beads, self.system.n_beads + 1]
        rigid = hoomd.md.constrain.Rigid()
        r_pos = self.snapshot.particles.position[0]
        c_pos = self.snapshot.particles.position[inds]
        c_pos -= r_pos
        c_pos = [tuple(i) for i in c_pos]
        c_types = [
                self.snapshot.particles.types[i] for
                i in self.snapshot.particles.typeid[inds]
        ]
        c_orient = [tuple(i) for i in self.snapshot.particles.orientation[inds]]
        c_charge = [i for i in self.snapshot.particles.charge[inds]]
        c_diam = [i for i in self.snapshot.particles.diameter[inds]]
        mass = np.array([self.system.bead_mass/2]*2)
        _moit = moit(c_pos, mass)
        self.snapshot.particles.moment_inertia[0:self.system.n_beads] = _moit

        rigid.body["R"] = {
                "constituent_types": c_types,
                "positions": c_pos,
                "orientations": c_orient,
                "charges": c_charge,
                "diameters": c_diam
        }
        rigid.create_bodies(self.sim.state) 
        # Set up hoomd groups 
        self.centers = hoomd.filter.Rigid()
        self.all = hoomd.filter.All()

        # Set up integrator; method is added in the 3 sim functions
        self.integrator = hoomd.md.Integrator(
                dt=dt, integrate_rotational_dof=True
        )
        self.integrator.forces = [gb, harmonic]
        self.integrator.rigid=rigid

        # Set up gsd and log writers
        gsd_writer, table_file = self._hoomd_writers(
                group=self.all, forcefields=[gb, harmonic]
        )
        self.sim.operations.writers.append(gsd_writer)
        self.sim.operations.writers.append(table_file)

    def shrink(self, kT, n_steps, shrink_period=10):
        """Run a shrink simulation to reach a target volume.

        Parameters
        ----------
        kT : float, required
            Temperature during shrink steps
        n_steps : int, required
            Number of simulations steps during shrinking
        shrink_period : int, optional, default=10
            Number of steps to run between box updates

        """
        # Set up box resizer
        box_resize_trigger = hoomd.trigger.Periodic(shrink_period)
        ramp = hoomd.variant.Ramp(
                A=0, B=1, t_start=0, t_ramp=int(n_steps)
        )
        self.target_box = hoomd.Box(
                Lx=self.system.target_box[0],
                Ly=self.system.target_box[1],
                Lz=self.system.target_box[2],
        )
        box_resize=hoomd.update.BoxResize(
                box1=self.sim.state.box,
                box2=self.target_box,
                variant=ramp,
                trigger=box_resize_trigger
        )
        self.sim.operations.updaters.append(box_resize)

        # Use NVT integrator during shrinking
        integrator_method = hoomd.md.methods.NVT(
                filter=self.centers, kT=kT, tau=self.tau
        )
        self.integrator.methods = [integrator_method]
        self.sim.operations.add(self.integrator)
        self.sim.state.thermalize_particle_momenta(filter=self.centers, kT=kT)
        self.sim.run(n_steps + 1) 
        self.ran_shrink = True

    def quench(self, kT, n_steps):
        """Run a simulation at a single temperature.

        Parameters
        ----------
        kT : float, required
            Temperature to run the simulation at.
        n_steps : int, required
            The number of simulation steps to run

        """
        if self.ran_shrink: # Shrink step ran, update temperature
            self.integrator.methods[0].kT = kT
        else: # Shrink not ran, add integrator method
            integrator_method = hoomd.md.methods.NVT(
                    filter=self.centers, kT=kT, tau=self.tau
            )
            self.integrator.methods = [integrator_method]
            self.sim.operations.add(self.integrator)

        self.sim.state.thermalize_particle_momenta(filter=self.centers, kT=kT)
        self.sim.run(n_steps)

    def anneal(
            self,
            kT_init=None,
            kT_final=None,
            step_sequence=None,
            schedule=None
    ):
        """Run a simulation over a range of temperatures.
        Give a starting and final temperature along with a step
        sequence to follow, or pass in an explicit schedule to follow.

        Parameters
        ----------
        kT_init : float, optional, defualt=None
            The starting temperature
        kT_final : float, optional, default=None
            The final temperature
        step_sequence : list of ints, optional, default=None
            the series of simulation steps to run between
            kT_init and kT_final
        schedule : dict, optional, default=None
            Use this instead of kT_init, kT_final and step_sequence
            to explicity set the series of temperatures and steps to run
            at each

        """
        if not self.ran_shrink: # Shrink not ran, add integrator method
            integrator_method = hoomd.md.methods.NVT(
                    filter=self.centers, kT=1.0, tau=self.tau
            )
            self.integrator.methods = [integrator_method]
            self.sim.operations.add(self.integrator)

        if not schedule:
            temps = np.linspace(kT_init, kT_final, len(step_sequence))
            temps = [np.round(t, 1) for t in temps]
            schedule = dict(zip(temps, step_sequence))

        for kT in schedule:
            self.integrator.methods[0].kT = kT
            self.sim.state.thermalize_particle_momenta(
                    filter=self.centers, kT=kT
            )
            self.sim.run(schedule[kT])

    def _hoomd_writers(self, group, forcefields):
        """Creates gsd and log writers"""
        # GSD and Logging:
        writemode = "w"
        gsd_writer = hoomd.write.GSD(
                filename="sim_traj.gsd",
                trigger=hoomd.trigger.Periodic(int(self.gsd_write)),
                mode=f"{writemode}b",
                dynamic=["momentum"]
        )

        logger = hoomd.logging.Logger(categories=["scalar", "string"])
        logger.add(self.sim, quantities=["timestep", "tps"])
        thermo_props = hoomd.md.compute.ThermodynamicQuantities(filter=group)
        self.sim.operations.computes.append(thermo_props)
        logger.add(thermo_props, quantities=self.log_quantities)
        for f in forcefields:
            logger.add(f, quantities=["energy"])

        table_file = hoomd.write.Table(
            output=open("sim_traj.txt", mode=f"{writemode}", newline="\n"),
            trigger=hoomd.trigger.Periodic(period=int(self.log_write)),
            logger=logger,
            max_header_len=None,
        )
        return gsd_writer, table_file
