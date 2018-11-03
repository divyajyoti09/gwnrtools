#!/usr/bin/env python
import matplotlib as mp
mp.use('pdf')
import sys
import os
import time
_itime = time.time()

import argparse
import numpy as np
import glob

from glue import gpstime
from glue.ligolw import ligolw
from glue.ligolw import table
from glue.ligolw import lsctables
from glue.ligolw import utils as ligolw_utils
from glue.ligolw.utils import process as ligolw_process

#ctx = CUDAScheme()

__author__ = "Prayush Kumar <prayush@astro.cornell.edu>"
PROGRAM_NAME = os.path.abspath(sys.argv[0])
#########################################################################
####################       Input parsing     #####################
#########################################################################
#{{{
parser = argparse.ArgumentParser(usage = "%%prog [OPTIONS]", description="""
Reads in all match files for given testpoint set against itself. Then:
0) match files are named as matches_sufficiently_far/match_A_B_A_D.dat, and:
   - A := testpoints_sufficiently_far/test_A.xml (is the testpoints ID)
   - B := testpoints_sufficiently_far_subparts/test_A_B.xml (is the subtestpoints ID)
   - D := testpoints_sufficiently_far_subparts/test_A_D.xml (is the subtestpoints ID)
1) match_file_name_glob will be matches_sufficiently_far/match_A_*.dat
2) Read in all match files
3) Sort all test points according to G = (no of points n with which the given
    point has match > [MM])
4) Keep the one with max(G)
5) Remove its nearest neighbors with which it had match > [MM]
6) Repeat steps 3)-5) till max(G) = 0
7) Add survivors to old bank
""", formatter_class=argparse.RawTextHelpFormatter)

# IO related inputs
parser.add_argument("--proposal-file-name",
                    dest="prop_file_name",
                    help="The current points file")
parser.add_argument("--old-bank-file-name",
                    dest="old_bank_file_name",
                    help="The old bank file")
parser.add_argument("--new-bank-file-name",
                    dest="new_bank_file_name",
                    help="The new points file")
parser.add_argument("--match-file-name-glob",
                    dest="match_file_name_glob",
                    help="glob for files that store matches")

# Physics related inputs
parser.add_argument("--minimal-match",
                    dest="mm",
                    default=0.97,
                    type=float)
parser.add_argument("--elimination-dir", metavar="STRING",
                    help="Where are hashes of eliminated proposals stored?",
                    default='testpoints_eliminated/')

# Miscellaneous
parser.add_argument("-V", "--verbose", action="store_true",
                    help="print extra debugging information",
                    default=False )
parser.add_argument("-C", "--comment", metavar="STRING",
                    help="add the optional STRING as the process:comment",
                    default='' )

options = parser.parse_args()
#}}}

#########################################################################
####################### Functions to do things         ##################
#########################################################################
# Miscellaneous
def get_tag(wav): return str(wav.simulation_id.column_name)

def is_eliminated(wav):
    sid = get_tag(wav)
    if os.path.exists(os.path.join(options.elimination_dir, sid)): return True
    return False

def parse_match_file(mfile_name,
                     mvals_for_each_bank_point = {},
                     mvals_for_each_test_point = {}):
    if not os.path.exists(mfile_name):
        raise IOError("Provided file {} not found.".format(mfile_name))
    with open(mfile_name, 'r') as mfile:
        for line in mfile.readlines():
            line = line.split()
            btag, ptag = line[:2]
            if btag not in mvals_for_each_bank_point:
                mvals_for_each_bank_point[btag] = {}
            if ptag not in mvals_for_each_bank_point[btag]:
                mvals_for_each_bank_point[btag][ptag] = line[-1]
            if ptag not in mvals_for_each_test_point:
                mvals_for_each_test_point[ptag] = {}
            if btag not in mvals_for_each_test_point[ptag]:
                mvals_for_each_test_point[ptag][btag] = line[-1]
    return mvals_for_each_bank_point, mvals_for_each_test_point

def get_all_matches_against_point(p, mvals_dict):
    mkeys = mvals_dict[p].keys()
    return np.array([mvals_dict[p][k] for k in mkeys], dtype=np.float128), mkeys

def get_all_G_values(mvals_dict):
    g_values = {}
    g_points = {}
    for p in mvals_dict:
        mvals, mpoints = get_all_matches_against_point(p, mvals_dict)
        high_mval_indices = np.where(mvals > options.mm)[0]
        g_points[p] = [mpoints[i] for i in high_mval_indices]
        g_values[p] = len(high_mval_indices)
    return g_values, g_points

#########################################################################
#################### Opening input/output files/tables ##################
#########################################################################
print "OPENING PROPOSAL FILE AND TABLES"
#{{{
# Open the input proposals file and get the table
if not options.prop_file_name:
    print "No proposal points file-name given!"
    raise ValueError("No proposal points file-name given to %s" % PROGRAM_NAME)

if not os.path.exists(options.prop_file_name):
    print "This proposal point file does not exist !"
    raise IOError(\
        "The proposal point file %s does not exist !" % options.prop_file_name)

print "Opening proposals file %s" % options.prop_file_name
prop_doc = ligolw_utils.load_filename(options.prop_file_name,
                  contenthandler=table.use_in(ligolw.LIGOLWContentHandler),
                  verbose=options.verbose)
try: prop_table = lsctables.SimInspiralTable.get_table(prop_doc)
except ValueError:
    raise IOError("Only sim_inspiral tables are understood for proposals..")

prop_table_tag_dict = {}
for p in prop_table: prop_table_tag_dict[get_tag(p)] = p

# Open the old bank file and get the table
if not options.old_bank_file_name:
    print "No old bank file-name given!"
    raise ValueError("No old bank file-name given to %s" % PROGRAM_NAME)

if not os.path.exists(options.old_bank_file_name):
    print "This bank file does not exist !"
    raise IOError(\
        "The bank point file %s does not exist !" % options.old_bank_file_name)

print "Opening bank file %s" % options.old_bank_file_name
old_bank_doc = ligolw_utils.load_filename(options.old_bank_file_name,
                  contenthandler=table.use_in(ligolw.LIGOLWContentHandler),
                  verbose=options.verbose)
try:
    old_bank_table = lsctables.SimInspiralTable.get_table(old_bank_doc)
except ValueError:
    raise IOError("Only sim_inspiral tables are understood for banks..")

# Open the output proposals file to write new table
outdoc = ligolw.Document()
outdoc.appendChild(ligolw.LIGO_LW())
new_inspiral_table = lsctables.New(lsctables.SimInspiralTable,
    columns=old_bank_table.columnnames)
outdoc.childNodes[0].appendChild(new_inspiral_table)
out_proc_id = ligolw_process.register_to_xmldoc(outdoc,
    PROGRAM_NAME, options.__dict__, comment=options.comment).process_id
outname = options.new_bank_file_name
for p in old_bank_table: new_inspiral_table.append(p)
#}}}

sys.stdout.flush()

#########################################################################
#############################   Remove eliminated pts   #################
#########################################################################

##########################################################
### Note on algorithm to follow:-
## 0) match files are named as matches_sufficiently_far/match_A_B_A_D.dat, and:
##    - A := testpoints_sufficiently_far/test_A.xml       (is the testpoints ID)
##    - B := testpoints_sufficiently_far_subparts/test_A_B.xml (is the subtestpoints ID)
##    - D := testpoints_sufficiently_far_subparts/test_A_D.xml (is the subtestpoints ID)
## 1) match_file_name_glob will be matches_sufficiently_far/match_A_*.dat
## 2) Read in all match files
## 3) Sort all test points according to G = (no of points n with which the given
## point has match > [MM])
## 4) Keep the one with max(G)
## 5) Remove its nearest neighbors with which it had match > [MM]
## 6) Repeat steps 3)-5) till max(G) = 0
## 7) Add survivors to old bank
##########################################################
## 1)
mfile_names = glob.glob(options.match_file_name_glob)
## 2)
mvals_for_each_bank_point = {}
mvals_for_each_test_point = {}
for mfile_name in mfile_names:
    mvals_for_each_bank_point, mvals_for_each_test_point =\
        parse_match_file(mfile_name, mvals_for_each_bank_point,\
            mvals_for_each_test_point)
# remove self-matches
for k in mvals_for_each_test_point:
    if k in mvals_for_each_test_point[k]:
        mvals_for_each_test_point[k].pop(k)
for k in mvals_for_each_bank_point:
    if k in mvals_for_each_bank_point[k]:
        mvals_for_each_bank_point[k].pop(k)
## 6)
## 3)
best_testpoints = []
gvals, gpoints  = get_all_G_values(mvals_for_each_test_point)
if len(gvals.values()) > 0: max_g_value = np.max(gvals.values())
else: max_g_value = -1
if options.verbose:
    print "Initially, all G values are: ", gvals.values()

while max_g_value > 0:
    ## 4)
    test_point_for_each_gval = {v:k for k,v in gvals.iteritems()}
    test_point_for_max_g_value = test_point_for_each_gval[max_g_value]
    best_testpoints.append(test_point_for_max_g_value)
    if options.verbose:
        print "\t maximum G value is {} for {}".format(max_g_value,\
            test_point_for_max_g_value)
        print "\t\t G-points include: ", gpoints[test_point_for_max_g_value]
    ## 5)
    if test_point_for_max_g_value in mvals_for_each_test_point:
        mvals_for_each_test_point.pop(test_point_for_max_g_value)
    for p in gpoints[test_point_for_max_g_value]:
        if p in mvals_for_each_test_point:
            mvals_for_each_test_point.pop(p)
        else: print "point {} to be removed not found!!".format(p)
    if options.verbose:
        print "\t\t removed {} points.".format(\
                                      len(gpoints[test_point_for_max_g_value]))
    ## 3)
    gvals, gpoints = get_all_G_values(mvals_for_each_test_point)
    max_g_value = np.max(gvals.values())
####
## 7)
for p in best_testpoints:
    new_inspiral_table.append(prop_table_tag_dict[p])
if options.verbose:
    print "\t N(best_testpoints) = {}".format(len(best_testpoints))

print "LEngth of prop_table_tag_dict = ", len(prop_table_tag_dict.keys())
print "LEngth of mvals_for_each_test_point = ",\
    len(mvals_for_each_test_point.keys())
for p in mvals_for_each_test_point:
    new_inspiral_table.append(prop_table_tag_dict[p])

##########################################################
# write the xml doc to disk
proctable = table.get_table(outdoc, lsctables.ProcessTable.tableName)
proctable[0].end_time = gpstime.GpsSecondsFromPyUTC(time.time())
ligolw_utils.write_filename(outdoc, outname)

cnt_additions = len(new_inspiral_table) - len(old_bank_table)
if options.verbose:
    print "Written results to file: {}".format(outname)
    print "Total {} test points added, {} total now.".format(cnt_additions,
        len(new_inspiral_table))
    print "Time taken: {} seconds".format(time.time() - _itime)
##
with open('SummaryStatistics.dat', 'a+') as fout:
    fout.write("%d\t%d\t%d\n" % (\
        int(options.old_bank_file_name.split('/')[-1].split('.')[0].split('_')[-1]),\
        len(new_inspiral_table) - len(old_bank_table), len(new_inspiral_table)))
    fout.flush()
