from polyellipsoid import Ellipsoid, Polymer
from polyellipsoid.utils import base_units

import hoomd
import gmso
import mbuild as mb
from mbuild.formats.hoomd_forcefield import to_hoomdsnapshot
import numpy as np

units = base_units.base_units()


class System:
    """
    """
    def __init__(
            self,
            n_chains,
            chain_lengths,
            bead_mass,
            density,
            axis_length,
            bond_length,
            major_axis=[1,0,0],
            seed=42,
    ):
        if not isinstance(n_chains, list):
            n_chains = [n_chains]
        if not isinstance(chain_lengths, list):
            chain_lengths = [chain_lengths]
        assert (
                len(n_chains) == len(chain_lengths)
        ), "n_chains and chain_lengths must be equal in length"

        self.n_chains = n_chains
        self.chain_lengths = chain_lengths
        self.bead_mass = bead_mass
        self.bond_length = bond_length
        self.density = density
        self.axis_length = axis_length
        self.major_axis = major_axis
        self.n_beads = sum([i*j for i,j in zip(n_chains, chain_lengths)])
        self.system_mass = bead_mass * self.n_beads
        self.target_box = None
        self.mb_system = None
        self.snapshot = None
        
        self.chains = []
        for l in chain_lengths:
            ellipsoid = Ellipsoid(
                    name="bead",
                    mass=self.bead_mass,
                    major_length=self.axis_length,
                    major_axis=self.major_axis,
            )
            chain = Polymer()
            chain.add_bead(
                    bead=ellipsoid,
                    bond_axis="major",
                    separation=self.bond_length
            )
            chain.build(n=l, add_hydrogens=False)
            self.chains.append(chain)

    def pack(self, box_expand_factor=5):
        """Uses mBuild's fill_box function to fill a cubic box
        with the ellipsoid chains. It may be necessary to expand
        the system volume during the packing step, and handling
        shrinking towards a target density during the simulation.

        Parameters
        ----------
        box_expand_factor : float, default=5
            The factor by which to expand the box edge lengths during
            the packing step. If PACKMOL fails, you may need to
            increase this parameter.

        """
        if self.target_box is None:
            self.set_target_box()
        pack_box = self.target_box * box_expand_factor
        system = mb.packing.fill_box(
            compound=self.chains,
            n_compounds=self.n_chains,
            box=list(pack_box),
            overlap=0.2,
            edge=0.9,
            fix_orientation=True
        )
        # TODO: Remove this attribute, using now for easy visualizing
        self.mb_system = system
        self.snapshot = self._make_rigid_snapshot(
                self._convert_to_parmed(system)
        )

    def stack(self, x, y, n, vector, z_axis_adjust=1.0):
        """Arranges chains in layers on an n x n lattice."""
        if self.n_chains[0] != n*n*2:
            raise ValueError(
                    "Using this method creates a system of n x n "
                    "unit cells with each unit cell containing 2 molecules. "
                    "The number of molecules in the system should equal "
                    f"2*n*n. You have {self.n_chains[0]} number of chains."
            )
        next_idx = 0
        system = mb.Compound()
        for i in range(n):
            layer = mb.Compound()
            for j in range(n): # Add chains to the layer along the y dir
                try:
                    chain1 = self.chains[next_idx]
                    chain2 = self.chains[next_idx + 1]
                    translate_by = np.array(vector)*(x, y, 0)
                    chain2.translate_by(translate_by)
                    cell = mb.Compound(subcompounds=[chain1, chain2])
                    cell.translate((0, y*j, 0))
                    layer.add(cell)
                    next_idx += 2
                except IndexError:
                    pass
            layer.translate((x*i, 0, 0)) # shift layers along x dir
            system.add(layer)

        bounding_box = system.get_boundingbox().lengths
        target_z = bounding_box[-1] * z_axis_adjust
        self.set_target_box(z_constraint=target_z)
        self.snapshot = self._make_rigid_snapshot(
                self._convert_to_parmed(system)
        )

    def set_target_box(
            self,
            x_constraint=None,
            y_constraint=None,
            z_constraint=None
    ):
        """Set the target volume of the system during
        the initial shrink step.
        If no constraints are set, the target box is cubic.
        Setting constraints will hold those box vectors
        constant and adjust others to match the target density.

        Parameters
        ----------
        x_constraint : float, optional, defualt=None
            Fixes the box length along the x axis
        y_constraint : float, optional, default=None
            Fixes the box length along the y axis
        z_constraint : float, optional, default=None
            Fixes the box length along the z axis

        """
        if not any([x_constraint, y_constraint, z_constraint]):
            Lx = Ly = Lz = self._calculate_L()
        else:
            constraints = np.array([x_constraint, y_constraint, z_constraint])
            fixed_L = constraints[np.where(constraints!=None)]
            #Conv from nm to cm for _calculate_L
            fixed_L /= units["cm_to_nm"]
            L = self._calculate_L(fixed_L = fixed_L)
            constraints[np.where(constraints==None)] = L
            Lx, Ly, Lz = constraints

        self.target_box = np.array([Lx, Ly, Lz])

    def _calculate_L(self, fixed_L=None):
        """Calculates the required box length(s) given the
        mass of a sytem and the target density.

        Box edge length constraints can be set by set_target_box().
        If constraints are set, this will solve for the required
        lengths of the remaining non-constrained edges to match
        the target density.

        Parameters
        ----------
        fixed_L : np.array, optional, defualt=None
            Array of fixed box lengths to be accounted for
            when solving for L

        """
        M = self.system_mass * units["amu_to_g"]  # grams
        vol = (M / self.density) # cm^3
        if fixed_L is None:
            L = vol**(1/3)
        else:
            L = vol / np.prod(fixed_L)
            if len(fixed_L) == 1: # L is cm^2
                L = L**(1/2)
        L *= units["cm_to_nm"]  # convert cm to nm
        return L

    def _convert_to_parmed(self, mb_system):
        """Uses gmso to add angles, and create a parmed object"""
        particle_mass = mb_system[0].mass
        sys_gmso = mb_system.to_gmso()
        sys_gmso.identify_connections()
        comp_pmd = gmso.external.to_parmed(sys_gmso)
        for a in comp_pmd.atoms:
            a.type = a.name
            a.mass = particle_mass
        return comp_pmd

    def _make_rigid_snapshot(self, pmd_system):
        """Handles requirements for setting up a snapshot
        to run a rigid body simulation in Hoomd.

        Parameters
        ----------
        pmd_system : required
            pmd system created by _convert_to_parmed 

        """
        init_snap = hoomd.Snapshot()
        init_snap.particles.types = ["R"]
        init_snap.particles.N = self.n_beads
        snapshot, refs = to_hoomdsnapshot(
                pmd_system, hoomd_snapshot=init_snap
        )
        snapshot.particles.mass[0:self.n_beads] = self.bead_mass
		# Get head-tail pair indices	
        pair_idx = [(i, i+1, i+2) for i in range(
            self.n_beads, snapshot.particles.N, 3 
        )]
        # Set position of rigid centers, set rigid body attr	
        for idx, pair in enumerate(pair_idx):
            pos1 = snapshot.particles.position[pair[0]]
            pos2 = snapshot.particles.position[pair[1]]
            pos3 = snapshot.particles.position[pair[2]]
            # Update rigid center position based on its constituent particles
            snapshot.particles.position[idx] = np.mean([pos1, pos2, pos3], axis=0)
            snapshot.particles.body[idx] = idx
            snapshot.particles.body[list(pair)] = idx * np.ones_like(pair)
        return snapshot	
