from django.core import management
from django.test import TestCase
from django.conf import settings
from cStringIO import StringIO
import sys
import os
from datetime import datetime
import ftplib
import urllib
import shutil
import time


class MonkeyPatch:

    # This class monkeypatches the network modules to provide a
    # controlled environment for testing.

    # The cullpdb files contain references to:
    #  - 1TWF
    #  - 3CGZ
    #  - 3CGX
    #  - 3CGM
    #  - 1MWW
    #  - 1H0H

    # For comparison, the database fixture contains:
    #  - 1TWF
    #  - 3CGZ
    #  - 1MWQ
    #  - 3CGM
    #  - 1MWW
    #  - 1H0H

    # Files for all seven proteins are available as well.

    @staticmethod
    def sitefile(filename):
        # All test files are stored in the same place.
        return os.path.join('pgd_splicer/testfiles', filename)

    @staticmethod
    def localfile(filename):
        # All local files are stored in the localdir.
        return os.path.join(settings.PDB_LOCAL_DIR, filename)

    class FTP:
        def __init__(self, host):
            self.host = host

        def login(self):
            pass

        def cwd(self, remotedir):
            pass

        def sendcmd(self, command):
            cmdlist = command.split(' ')
            if cmdlist[0] == 'MDTM':
                filename = cmdlist[1]
                try:
                    rawmtime = os.path.getmtime(MonkeyPatch.sitefile(filename))
                    rawstamp = datetime.fromtimestamp(rawmtime)
                    # return 20090301142529 for '03/01/2009 14:25:29 GMT'
                    return "213 %s" % rawstamp.strftime('%Y%m%d%H%M%S')
                except OSError:
                    # If file does not exist, the FTP server will
                    # return a permanent error.

                    # NB: should be error_perm but we will use False
                    return False
            else:
                # NB: Raise exception if unsupported command is used.
                return False

        def size(self, filename):
            # If the file exists, return its size.  If it doesn't, return None.
            try:
                return os.path.getsize(MonkeyPatch.sitefile(filename))
            except OSError:
                return None

        def retrbinary(self, command, callback, blocksize=8192, rest='REST'):
            # If the file exists, 'download' it.  If it doesn't, return False.
            cmdlist = command.split(' ')
            if cmdlist[0] == 'RETR':
                filename = cmdlist[1]
                try:
                    with open(MonkeyPatch.sitefile(filename)) as f:
                        while 1:
                            data = f.read(blocksize)
                            if not data:
                                break
                            callback(data)
                except OSError:
                    return False
            else:
                # NB: Raise exception if unsupported command is used.
                return False

    class urlopen:
        def __init__(self, url, data=None, proxies=None):
            # List of known URLs and their corresponding files.
            baseURL = 'http://dunbrack.fccc.edu/Guoli/culledpdb/'
            pc25 = baseURL + '/cullpdb_pc25_res3.0_R1.0_d130614_chains8184.gz'
            pc90 = baseURL + '/cullpdb_pc90_res3.0_R1.0_d130614_chains24769.gz'
            knownurls = {baseURL: 'selection_page.txt',
                         pc25: 'cullpdb_pc25.gz',
                         pc90: 'cullpdb_pc90.gz'}

            self.url = url
            if self.url in knownurls:
                self.fileobj = open(MonkeyPatch.sitefile(knownurls[self.url]))
            else:
                self.fileobj = None

        def read(self):
            if self.fileobj is None:
                return None
            else:
                return self.fileobj.read()

        def readline(self):
            if self.fileobj is None:
                return None
            else:
                return self.fileobj.readline()

        def readlines(self):
            if self.fileobj is None:
                return None
            else:
                return self.fileobj.readlines()

        def fileno(self):
            if self.fileobj is None:
                return None
            else:
                return self.fileobj.fileno()

        def close(self):
            if self.fileobj is None:
                return None
            else:
                return self.fileobj.close()

        def info(self):
            if self.fileobj is None:
                return None
            else:
                return self.fileobj.info()

        def getcode(self):
            if self.fileobj is None:
                return 404
            else:
                return 200

        def geturl(self):
            return url

    def __enter__(self):
        # Override existing FTP and urlopen with our versions.
        self.old_FTP = ftplib.FTP
        ftplib.FTP = MonkeyPatch.FTP
        self.old_urlopen = urllib.urlopen
        urllib.urlopen = MonkeyPatch.urlopen

        if not os.path.exists(settings.PDB_LOCAL_DIR):
            os.makedirs(settings.PDB_LOCAL_DIR)

        # Replace all PDB entries with our test entries.
        # JMT: consider making a separate 'testpdb' directory?
        codes = ['1mwq', '1mww', '1twf', '3cgm', '3cgx', '3cgz', '1h0h']
        for code in codes:
            pdbfile = 'pdb%s.ent.gz' % code
            if os.path.exists(MonkeyPatch.sitefile(pdbfile)):
                shutil.copyfile(MonkeyPatch.sitefile(pdbfile),
                                MonkeyPatch.localfile(pdbfile))
                shutil.copystat(MonkeyPatch.sitefile(pdbfile),
                                MonkeyPatch.localfile(pdbfile))
            else:
                print "%s: site file does not exist, oh no!"

    def __exit__(self, type, value, traceback):
        # Clean up overrides
        ftplib.FTP = self.old_FTP
        urllib.urlopen = self.old_urlopen


class ManagementCommands(TestCase):

    fixtures = ['pgd_core']

    def setUp(self):
        self.out = StringIO()
        self.err = StringIO()

    def test_fetch_old(self):
        # How far into the past do we set the test files?
        howfar = 86400 * 365 * 10

        # This requires the 3CGX protein file but does not require the
        # 1MWQ protein file.
        proteins = {'3cgx': 'pdb/pdb3cgx.ent.gz',
                    '1mwq': 'pdb/pdb1mwq.ent.gz'}

        # The original modification times of the files.
        newdates = {}

        # The modification times of the files after they are set into the past.
        olddates = {}

        # The modification times after the management command returns.
        postdates = {}

        # The management command should ignore 1MWQ and add 3CGX.
        with MonkeyPatch():

            # Set the file dates back!
            for key in proteins:
                olddates[key] = int(os.path.getmtime(proteins[key]))
                os.utime(proteins[key], (-1, olddates[key] - howfar))

            # Run the management command.
            management.call_command('fetch', stdout=self.out)

            # Record the file dates now.
            for key in proteins:
                postdates[key] = int(os.path.getmtime(proteins[key]))

            # Only the 3CGX file should have been updated.
            self.assertEqual(postdates['3cgx'], int(time.time()))
            self.assertLess(postdates['1mwq'], olddates['1mwq'])

            # The 3CGX file should be larger than 8192 bytes.
            self.assertGreater(os.path.getsize(proteins['3cgx']), 8192)

    def test_fetch_missing(self):

        # This requires the 3CGX protein file but does not require the
        # 1MWQ protein file.
        proteins = {'3cgx': 'pdb/pdb3cgx.ent.gz',
                    '1mwq': 'pdb/pdb1mwq.ent.gz'}

        with MonkeyPatch():
            # The management command should ignore 1MWQ and add 3CGX.

            # Remove the files if they exists.
            for key in proteins:
                if os.path.exists(proteins[key]):
                    os.remove(proteins[key])

            # Run the management command.
            management.call_command('fetch', stdout=self.out)

            # Only the 3CGX file should now exist.
            self.assertTrue(os.path.exists(proteins['3cgx']))
            self.assertFalse(os.path.exists(proteins['1mwq']))

            # The 3CGX file should be larger than 8192 bytes.
            self.assertGreater(os.path.getsize(proteins['3cgx']), 8192)

    @staticmethod
    def file_to_dict(infile):
        my_dict = {}
        with open(infile) as data:
            for line in data:
                words = line.split()
                if words[0] == 'VERSION:':
                    continue
                my_dict[words[0]] = words[1:]
        return my_dict

    def test_fetch_selection(self):

        with MonkeyPatch():
            # The original selection file, with bad 1MWQ and no 3CGX.
            good_selection = MonkeyPatch.sitefile('fixture_selection.txt')
            good_dict = self.file_to_dict(good_selection)
            # Remove 1MWQ.
            del good_dict['1MWQ']
            # Add 3CGX.
            good_dict['3CGX'] = ['A', '25', '1.900', '0.17', '0.21']
            test_selection = MonkeyPatch.localfile('test_selection.txt')
            management.call_command('fetch', stdout=self.out, selection=test_selection)
            test_dict = self.file_to_dict(test_selection)
            self.assertEqual(good_dict, test_dict)
            if os.path.exists(test_selection):
                os.remove(test_selection)

    def test_crosscheck_fixture(self):

        # Cross-check the database against the fixture selection.txt file.
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        selection = MonkeyPatch.sitefile('fixture_selection.txt')
        management.call_command('crosscheck', [],
                                selection=selection, verbose=True)
        test_out = sys.stdout.getvalue()
        sys.stdout.close()
        sys.stdout = old_stdout

        good_out = MonkeyPatch.sitefile('fixture_crosscheck.txt')
        self.assertEqual(test_out, file(good_out).read())

    def test_crosscheck_cullpdb(self):

        # Cross-check the database against the cullpdb selection.txt file.
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        selection = MonkeyPatch.sitefile('cullpdb_selection.txt')
        management.call_command('crosscheck', [],
                                selection=selection, verbose=True)
        test_out = sys.stdout.getvalue()
        sys.stdout.close()
        sys.stdout = old_stdout

        good_out = MonkeyPatch.sitefile('cullpdb_crosscheck.txt')
        self.assertEqual(test_out, file(good_out).read())
