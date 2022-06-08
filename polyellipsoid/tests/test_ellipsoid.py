from polyellipsoid import Simulation, Ellipsoid
from base_test import BaseTest

import numpy as np
import pytest

class TestEllipsoid(BaseTest):

    def test_make_ellipsoid(self):
        bead = Ellipsoid(name="A", mass=100, major_length=2.0)
        assert [p.name for p in bead.particles()] == ["CH", "CC", "CT"]
        assert np.array_equal(bead[0].xyz[0], np.array([1.0, 0, 0]))
        assert np.array_equal(bead[1].xyz[0], np.array([0, 0, 0]))
        assert np.array_equal(bead[2].xyz[0], np.array([-1.0, 0, 0]))
        assert bead.n_bonds == 1
        
