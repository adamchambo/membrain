"""PCA of latest explanation vectors for display; distance is not a prerequisite."""

import math


def embedding_positions(vectors: list[list[float]]) -> list[dict]:
    """Return x, y, z for each vector from a centred Gram-matrix PCA.

    With fewer than four points, unused axes stay 0 (a point, a line, a plane).
    Eigenvector signs are fixed so the same vectors always lay out the same way.
    """
    n = len(vectors)
    if n == 0:
        return []
    dimension = len(vectors[0])
    mean = [sum(row[axis] for row in vectors) / n for axis in range(dimension)]
    centred = [[row[axis] - mean[axis] for axis in range(dimension)] for row in vectors]
    gram = [[sum(centred[i][k] * centred[j][k] for k in range(dimension)) for j in range(n)] for i in range(n)]
    values, columns = _jacobi(gram)
    order = sorted(range(n), key=lambda index: values[index], reverse=True)[:3]
    axes = []
    for index in order:
        scale = math.sqrt(values[index]) if values[index] > 1e-12 else 0.0
        column = [columns[row][index] for row in range(n)]
        pivot = next((entry for entry in column if abs(entry) > 1e-9), 0.0)
        if pivot < 0:
            column = [-entry for entry in column]
        axes.append([scale * entry for entry in column])
    while len(axes) < 3:
        axes.append([0.0] * n)
    return [{"x": axes[0][i], "y": axes[1][i], "z": axes[2][i]} for i in range(n)]


def _jacobi(matrix: list[list[float]]) -> tuple[list[float], list[list[float]]]:
    """Symmetric eigen-decomposition; columns of the second result are eigenvectors."""
    n = len(matrix)
    values = [row[:] for row in matrix]
    vectors = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for _ in range(64):
        off, p, q = 0.0, 0, 1
        for i in range(n):
            for j in range(i + 1, n):
                if abs(values[i][j]) > off:
                    off, p, q = abs(values[i][j]), i, j
        if off < 1e-12:
            break
        app, aqq, apq = values[p][p], values[q][q], values[p][q]
        tau = (aqq - app) / (2 * apq)
        t = math.copysign(1 / (abs(tau) + math.sqrt(1 + tau * tau)), tau)
        c = 1 / math.sqrt(1 + t * t)
        s = t * c
        for i in range(n):
            if i != p and i != q:
                aip, aiq = values[i][p], values[i][q]
                values[i][p] = values[p][i] = c * aip - s * aiq
                values[i][q] = values[q][i] = s * aip + c * aiq
            vip, viq = vectors[i][p], vectors[i][q]
            vectors[i][p] = c * vip - s * viq
            vectors[i][q] = s * vip + c * viq
        values[p][p] = c * c * app - 2 * s * c * apq + s * s * aqq
        values[q][q] = s * s * app + 2 * s * c * apq + c * c * aqq
        values[p][q] = values[q][p] = 0.0
    return [values[i][i] for i in range(n)], vectors
