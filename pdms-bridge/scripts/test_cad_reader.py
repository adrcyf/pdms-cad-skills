import pathlib
import tempfile
import unittest
import ezdxf


class CadTests(unittest.TestCase):
    def test_reads_geometry_and_separates_dimension_override(self):
        from cad_reader import CadReader
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'fixture.dxf'
            doc = ezdxf.new('R2018')
            doc.units = 4
            model = doc.modelspace()
            model.add_circle((10, 20), 5)
            model.add_line((0, 0), (30, 40))
            dim = model.add_linear_dim(base=(0, 10), p1=(0, 0), p2=(100, 0), text='80')
            dim.render()
            doc.saveas(path)
            reader = CadReader(path)
            self.assertEqual(reader.query(types=['CIRCLE'])['entities'][0]['radius'], 5)
            self.assertEqual(reader.query(types=['LINE'], include_blocks=False)['entities'][0]['length'], 50)
            result = reader.query(types=['DIMENSION'])['entities'][0]
            self.assertEqual(result['geometry_measurement'], 100)
            self.assertEqual(result['text_override'], '80')

    def test_block_transform_and_filter_pagination(self):
        from cad_reader import CadReader
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'fixture.dxf'
            doc = ezdxf.new('R2018')
            block = doc.blocks.new('TEST')
            block.add_circle((1, 0), 2)
            doc.modelspace().add_blockref('TEST', (10, 20), dxfattribs={'xscale': 2, 'yscale': 2, 'zscale': 2})
            doc.saveas(path)
            result = CadReader(path).query(types=['CIRCLE'], limit=1)
            self.assertEqual(result['entities'][0]['center'][:2], [12, 20])
            self.assertEqual(result['entities'][0]['radius'], 4)
            self.assertTrue(result['entities'][0]['virtual'])


if __name__ == '__main__':
    unittest.main()
