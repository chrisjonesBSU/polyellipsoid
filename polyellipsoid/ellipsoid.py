from mbuild import Compound


class Ellipsoid(Compound):
    def __init__(self, mass, length):
        """Creates a single ellipsoid monomer with the required ghost 
        particles and rigid center. This class is called by the
        polyellipsoid.System() when creating ellipsoid chains.

        Parameters
        ----------
        mass : float; required
            The mass of the ellipsoid bead in amu
        length : float; required
            The length of the ellipsoid bead along the bonding axis (nm)

        """
        super(Ellipsoid, self).__init__(name="ellipsoid")
        # Convert length to nm while in mBuild space
        self.length = float(length) / 10
        # Create the constituent particles
        self.head = Compound(
                pos=[self.length/2, 0, 0],
                name="A",
                mass=mass/4
        )
        self.tail = Compound(
                pos=[-self.length/2, 0, 0],
                name="A",
                mass=mass/4
        )
        self.head_mid = Compound(
                pos=[self.length/4, 0, 0],
                name="B",
                mass=mass/4
        )
        self.tail_mid = Compound(
                pos=[-self.length/4, 0, 0],
                name="B",
                mass=mass/4
        )
        self.add([self.head, self.tail, self.head_mid, self.tail_mid])
