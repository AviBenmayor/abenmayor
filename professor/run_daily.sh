#!/bin/bash
# Professor Daily Run Script
# Runs the full pipeline and logs output

cd /Users/abenmayor/Documents/Projects/abenmayor/professor
/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3 cli.py run >> /Users/abenmayor/Documents/Projects/abenmayor/professor/data/professor.log 2>&1
