"""PCA placement is deterministic and uses as many axes as the points support."""

import unittest

from app.discovery.layout import embedding_positions


class LayoutTests(unittest.TestCase):
    def test_orthogonal_vectors_separate_and_repeat(self):
        vectors = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        first = embedding_positions(vectors)
        second = embedding_positions(vectors)
        self.assertEqual(first, second)
        pairs = [(0, 1), (0, 2), (1, 2)]
        for i, j in pairs:
            distance = sum((first[i][axis] - first[j][axis]) ** 2 for axis in ("x", "y", "z"))
            self.assertGreater(distance, 0.1)

    def test_one_vector_is_the_origin_and_two_lie_on_a_line(self):
        origin = embedding_positions([[1.0, 0.0, 0.0]])[0]
        self.assertEqual((origin["x"], origin["y"], origin["z"]), (0.0, 0.0, 0.0))
        line = embedding_positions([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        self.assertTrue(all(abs(point["z"]) < 1e-9 for point in line))
        self.assertGreater(abs(line[0]["x"] - line[1]["x"]) + abs(line[0]["y"] - line[1]["y"]), 0.1)
