"""PCA placement is deterministic and uses as many axes as the points support."""

import random
import unittest

from app.discovery.layout import _jacobi, embedding_positions


class LayoutTests(unittest.TestCase):
    def test_orthogonal_vectors_separate_and_repeat(self):
        vectors = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        first = embedding_positions(vectors)
        second = embedding_positions(vectors)
        self.assertEqual(first, second)
        self.assertTrue(all(abs(point["z"]) < 1e-9 for point in first))
        pairs = [(0, 1), (0, 2), (1, 2)]
        for i, j in pairs:
            distance = sum((first[i][axis] - first[j][axis]) ** 2 for axis in ("x", "y", "z"))
            self.assertGreater(distance, 0.1)

    def test_four_orthogonal_vectors_use_the_third_axis(self):
        positions = embedding_positions([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ])
        self.assertGreater(max(abs(point["z"]) for point in positions), 0.1)

    def test_thirty_vectors_converge_and_repeat(self):
        random.seed(1)
        vectors = [[random.uniform(-1, 1) for _ in range(8)] for _ in range(30)]
        n, dimension = len(vectors), len(vectors[0])
        mean = [sum(row[axis] for row in vectors) / n for axis in range(dimension)]
        centred = [[row[axis] - mean[axis] for axis in range(dimension)] for row in vectors]
        gram = [[sum(centred[i][k] * centred[j][k] for k in range(dimension)) for j in range(n)] for i in range(n)]
        values, columns = _jacobi(gram)
        largest = sorted(range(n), key=lambda index: values[index], reverse=True)[:3]
        for index in largest:
            column = [columns[row][index] for row in range(n)]
            product = [sum(gram[row][col] * column[col] for col in range(n)) for row in range(n)]
            residual = sum((product[row] - values[index] * column[row]) ** 2 for row in range(n)) ** 0.5
            self.assertLess(residual, 1e-6)
        self.assertEqual(embedding_positions(vectors), embedding_positions(vectors))

    def test_one_vector_is_the_origin_and_two_lie_on_a_line(self):
        origin = embedding_positions([[1.0, 0.0, 0.0]])[0]
        self.assertEqual((origin["x"], origin["y"], origin["z"]), (0.0, 0.0, 0.0))
        line = embedding_positions([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        self.assertTrue(all(abs(point["z"]) < 1e-9 for point in line))
        self.assertGreater(abs(line[0]["x"] - line[1]["x"]) + abs(line[0]["y"] - line[1]["y"]), 0.1)
