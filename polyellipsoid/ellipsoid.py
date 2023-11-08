from mbuild import Compound
from mbuild.lib.recipes.polymer import Polymer


class Ellipsoid(Compound):
    def __init__(self, mass, length):
        super(Ellipsoid, self).__init__(name="ellipsoid")
        self.length = float(length)
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


class Chain(Polymer):
    def __init__(self, length, bead_mass, bead_length, bond_length):
        super(Chain, self).__init__()
        bead = Ellipsoid(mass=bead_mass, length=bead_length)
        self.add_monomer(
                bead,
                indices=[0, 1],
                orientation=[[1,0,0], [-1,0,0]],
                replace=False,
                separation=bond_length
        )
        self.build(n=length, add_hydrogens=False)
