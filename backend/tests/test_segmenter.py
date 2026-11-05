"""Offline numerical regressions; extract pure helpers without model dependencies."""
import ast
from pathlib import Path
import unittest
import numpy as np

SOURCE = Path(__file__).resolve().parents[1] / 'vision' / 'anatomy' / 'optic_disc_cup.py'
tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
helpers = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {'overlay', 'cup_to_disc_ratio'}]
namespace = {'np': np}
exec(compile(ast.Module(body=helpers, type_ignores=[]), str(SOURCE), 'exec'), namespace)

class SegmenterTests(unittest.TestCase):
    def test_background_and_colors(self):
        image = np.full((2, 2, 3), 100, dtype=np.uint8)
        mask = np.array([[0, 1], [2, 0]])
        result = namespace['overlay'](image, mask)
        np.testing.assert_array_equal(result[mask == 0], image[mask == 0])
        np.testing.assert_array_equal(result[0, 1], [178, 50, 100])
        np.testing.assert_array_equal(result[1, 0], [50, 178, 50])
        self.assertTrue(np.all(image == 100))
        np.testing.assert_array_equal(namespace['overlay'](image, mask, 0), image)
        with self.assertRaises(ValueError):
            namespace['overlay'](image, mask, float('nan'))

    def test_ratio(self):
        ratio = namespace['cup_to_disc_ratio']
        self.assertEqual(ratio(np.array([[1, 1, 1, 2]])), 0.5)
        self.assertEqual(ratio(np.array([[1]])), 0.0)
        self.assertEqual(ratio(np.array([[2]])), 1.0)
        with self.assertRaises(ValueError):
            ratio(np.zeros((2, 2)))

if __name__ == '__main__':
    unittest.main()
