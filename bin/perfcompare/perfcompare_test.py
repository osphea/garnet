# Copyright 2019 The Fuchsia Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import StringIO
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import unittest

import perfcompare


# Test case helper class for creating temporary directories that will
# be cleaned up when the test finishes.
class TempDirTestCase(unittest.TestCase):

    def setUp(self):
        self._on_teardown = []

    def MakeTempDir(self):
        temp_dir = tempfile.mkdtemp(
            prefix='tmp_unittest_%s_' % self.__class__.__name__)
        def tear_down():
            shutil.rmtree(temp_dir)
        self._on_teardown.append(tear_down)
        return temp_dir

    def tearDown(self):
        for func in reversed(self._on_teardown):
            func()


def WriteJsonFile(filename, json_data):
    with open(filename, 'w') as fh:
        json.dump(json_data, fh)


def ReadGoldenFile(filename):
    data = open(filename, 'r').read()
    matches = list(re.finditer('\n\n### (.*)\n', data, re.M))
    starts = [m.end() for m in matches]
    ends = [m.start() for m in matches[1:]] + [len(data)]
    for m, start, end in zip(matches, starts, ends):
        yield m.group(1), data[start:end]


# Helper for checking against test expectations in a golden file.
# This provides an implementation of AssertCaseEq() that compares
# results against the golden file.
class GoldenDataInput(object):

    def __init__(self, filename):
        self._cases = dict(ReadGoldenFile(filename))

    def AssertCaseEq(self, name, actual):
        expected = self._cases[name]
        if expected != actual:
            raise AssertionError('"%s" != "%s"' % (actual, expected))


# This provides an implementation of AssertCaseEq() that updates the
# golden file with new expectations generated by the tests.
class GoldenDataOutput(object):

    def __init__(self):
        self._cases = {}

    def AssertCaseEq(self, name, actual):
        assert name not in self._cases, name
        self._cases[name] = actual

    def WriteFile(self, filename):
        with open(filename, 'w') as fh:
            for name, data in sorted(self._cases.iteritems()):
                fh.write('\n\n### %s\n%s' % (name, data))


GOLDEN_FILE = os.path.join(os.path.dirname(__file__),
                           'perfcompare_test_output.txt')
GOLDEN = GoldenDataInput(GOLDEN_FILE)


def TestMain():
    global GOLDEN
    if '--generate' in sys.argv:
        sys.argv.pop(sys.argv.index('--generate'))
        GOLDEN = GoldenDataOutput()
        try:
            unittest.main()
        finally:
            GOLDEN.WriteFile(GOLDEN_FILE)
    else:
        unittest.main()


# Test data from a normal distribution, generated using the following code:
# ', '.join('%.4f' % random.gauss(0, 1) for _ in xrange(100))
TEST_VALUES = [
    0.4171, 2.1056, -0.0223, -1.6592, 0.4766, -0.6405, 0.3488, 1.5729,
    2.0654, -0.1324, -0.8648, -0.2793, -0.7966, 0.2851, -0.9374, -2.0275,
    0.8222, -0.2396, -0.6982, 0.9067, 0.9416, -2.2870, -0.1868, 1.0700,
    -1.2531, 0.8455, 1.4755, 0.2979, 0.3441, 0.6694, -0.1808, -0.9038,
    0.8267, -0.4320, -0.7166, 0.3757, -0.5135, -0.9497, 2.0372, -0.3364,
    0.3879, -0.2970, 1.3872, 0.6538, 1.0674, 1.2349, -0.6873, -0.1807,
    0.6867, -0.1150, -1.0526, -0.6853, -0.5858, -1.8460, 1.6041, -1.1638,
    0.5459, -1.6476, -0.8711, -0.9001, 0.0788, -0.8170, 0.2439, 0.0129,
    -0.8674, -1.1076, -0.0074, -0.6230, -0.4761, -2.2526, 0.4906, -0.5001,
    -0.2050, 0.7623, -0.5511, -0.2837, -0.8797, -0.5374, -1.2910, 0.9551,
    0.4483, -0.6352, -0.3334, -0.5105, 0.1073, 2.9131, -0.4941, -0.2808,
    -0.2517, -1.9961, 0.9214, -0.6325, -1.1895, 0.8118, 1.5424, 0.5601,
    -1.0322, 0.7135, -0.2780, -0.1128]

def GenerateTestData(mean, stddev):
    return [x * stddev + mean for x in TEST_VALUES]


class PerfCompareTest(TempDirTestCase):

    def WriteExampleDataDir(self, dir_path, mean=1000, stddev=100,
                            drop_one=False):
        results = [('ClockGetTimeExample', GenerateTestData(mean, stddev))]
        if not drop_one:
            results.append(('SecondExample', GenerateTestData(2000, 300)))

        for test_name, values in results:
            for idx, value in enumerate(values):
                WriteJsonFile(
                    os.path.join(dir_path, '%s_%d.json' % (test_name, idx)),
                    [{'label': test_name,
                      'test_suite': 'fuchsia.example.perf_test',
                      'unit': 'nanoseconds',
                      'values': [value]}])

        # Include a summary.json file to check that we skip reading it.
        with open(os.path.join(dir_path, 'summary.json'), 'w') as fh:
            fh.write('dummy_data')
        # Include a *.catapult_json file to check that we skip reading these.
        with open(os.path.join(dir_path, 'foo.catapult_json'), 'w') as fh:
            fh.write('dummy_data')

    def ExampleDataDir(self, **kwargs):
        dir_path = self.MakeTempDir()
        self.WriteExampleDataDir(dir_path, **kwargs)
        return dir_path

    def test_reading_results_from_dir(self):
        dir_path = self.ExampleDataDir()
        results = perfcompare.ResultsFromDir(dir_path)
        self.assertEquals(
            results['ClockGetTimeExample'].FormatConfidenceInterval(),
            '991 +/- 26')

    def test_reading_results_from_multi_boot_dir(self):
        dir_path = self.MakeTempDir()
        subdir = os.path.join(dir_path, 'by_boot', 'boot000000')
        os.makedirs(subdir)
        self.WriteExampleDataDir(subdir)
        results = perfcompare.ResultsFromDir(dir_path)
        self.assertEquals(
            results['ClockGetTimeExample'].FormatConfidenceInterval(),
            '991 +/- 26')

    def test_reading_results_from_tar_file(self):
        dir_path = self.ExampleDataDir()
        # Test the uncompressed and gzipped cases.
        for write_mode in ('w', 'w:gz'):
            # Create a tar file containing the example results files.
            tar_filename = os.path.join(self.MakeTempDir(), 'out.tar')
            with tarfile.open(tar_filename, write_mode) as tar:
                for name in os.listdir(dir_path):
                    tar.add(os.path.join(dir_path, name), arcname=name)
            results = perfcompare.ResultsFromDir(tar_filename)
            self.assertEquals(
                results['ClockGetTimeExample'].FormatConfidenceInterval(),
                '991 +/- 26')

    # Returns the output of compare_perf when run on the given directories.
    def ComparePerf(self, before_dir, after_dir):
        stdout = StringIO.StringIO()
        perfcompare.Main(['compare_perf', before_dir, after_dir], stdout)
        return stdout.getvalue()

    def test_mean_and_stddev(self):
        values = [10, 5, 15]
        mean_val, stddev_val = perfcompare.MeanAndStddev(values)
        self.assertEquals(mean_val, 10.0)
        self.assertEquals(perfcompare.Mean(values), 10.0)
        self.assertEquals(stddev_val, 5.0)
        # Check error cases.
        self.assertRaises(lambda: perfcompare.Mean([]))
        self.assertRaises(lambda: perfcompare.MeanAndStddev([]))
        self.assertRaises(lambda: perfcompare.MeanAndStddev([100]))

    # Check that data written using the golden file helper reads back
    # the same.
    def test_golden_file_write_and_read(self):
        temp_file = os.path.join(self.MakeTempDir(), 'file')
        writer = GoldenDataOutput()
        writer.AssertCaseEq('a_key', 'a_value')
        writer.AssertCaseEq('b_key', 'line 1\n' 'line 2\n')
        writer.WriteFile(temp_file)
        reader = GoldenDataInput(temp_file)
        reader.AssertCaseEq('a_key', 'a_value')
        reader.AssertCaseEq('b_key', 'line 1\n' 'line 2\n')
        self.assertRaises(lambda: reader.AssertCaseEq('a_key', 'other_value'))

    def test_comparison_no_change(self):
        before_dir = self.ExampleDataDir()
        after_dir = self.ExampleDataDir()
        output = self.ComparePerf(before_dir, after_dir)
        GOLDEN.AssertCaseEq('comparison_no_change', output)

    # Test a regression that is large enough to be flagged.
    def test_comparison_regression(self):
        before_dir = self.ExampleDataDir(mean=1500, stddev=100)
        after_dir = self.ExampleDataDir(mean=1600, stddev=100)
        output = self.ComparePerf(before_dir, after_dir)
        GOLDEN.AssertCaseEq('comparison_regression', output)

    # Test an improvement that is large enough to be flagged.
    def test_comparison_improvement(self):
        before_dir = self.ExampleDataDir(mean=1500, stddev=100)
        after_dir = self.ExampleDataDir(mean=1400, stddev=100)
        output = self.ComparePerf(before_dir, after_dir)
        GOLDEN.AssertCaseEq('comparison_improvement', output)

    # Test an improvement that is not large enough to be flagged.
    def test_comparison_improvement_small(self):
        before_dir = self.ExampleDataDir(mean=1500, stddev=100)
        after_dir = self.ExampleDataDir(mean=1450, stddev=100)
        output = self.ComparePerf(before_dir, after_dir)
        GOLDEN.AssertCaseEq('comparison_improvement_small', output)

    def test_adding_test(self):
        before_dir = self.ExampleDataDir(drop_one=True)
        after_dir = self.ExampleDataDir()
        output = self.ComparePerf(before_dir, after_dir)
        GOLDEN.AssertCaseEq('adding_test', output)

    def test_removing_test(self):
        before_dir = self.ExampleDataDir()
        after_dir = self.ExampleDataDir(drop_one=True)
        output = self.ComparePerf(before_dir, after_dir)
        GOLDEN.AssertCaseEq('removing_test', output)

    def test_mismatch_rate(self):
        self.assertEquals(perfcompare.MismatchRate([(0,1), (2,3)]), 1)
        self.assertEquals(perfcompare.MismatchRate([(0,2), (1,3)]), 0)
        self.assertEquals(perfcompare.MismatchRate([(0,2), (1,3), (4,5)]), 2./3)

    def test_validate_perfcompare(self):
        # This is an example input dataset that gives a high mismatch rate,
        # because the data is drawn from two very different distributions.
        results_dirs = ([self.ExampleDataDir(mean=100, stddev=10)] * 10 +
                        [self.ExampleDataDir(mean=200, stddev=10)] * 10)
        stdout = StringIO.StringIO()
        perfcompare.Main(['validate_perfcompare'] + results_dirs, stdout)
        output = stdout.getvalue()
        GOLDEN.AssertCaseEq('validate_perfcompare', output)


if __name__ == '__main__':
    TestMain()