import os

import pytest
from polyellipsoid import Ellipsoid, Polymer, System, Simulation

class BaseTest:
    @pytest.fixture(autouse=True)
    def initdir(self, tmpdir):
        tmpdir.chdir()
    
    @pytest.fixture
    def bead(self):
        return Ellipsoid("A", 100, 2)

    @pytest.fixture
    def packed_system(self):
        return self.make_system(method="pack")

    @pytest.fixture
    def stacked_system(self):
        return self.make_system(method="stack")
    
    @pytest.fixture
    def sim_init(self):
        sys = self.make_system(method="pack")
        sim = Simulation(
                system=sys,
                lperp=0.5,
                lpar=1.0,
                epsilon=5,
                tau=0.01,
                dt=0.001,
                r_cut=2.5,
                bond_k=1000,
                angle_k=500,
                theta0=2.5,
                seed=42,
                gsd_write=10000,
                log_write=100
        )
        return sim

    def make_system(self, method):
        sys = System(
                n_chains=20,
                chain_lengths=5,
                bead_mass=100,
                density=0.05,
                bond_length=0.10,
                axis_length=1
        )
        if method == "pack":
            sys.pack(box_expand_factor=5)
        elif method == "stack":
            sys.stack(x=2, y=2, axis=[1,1,0], n=2)
        return sys
