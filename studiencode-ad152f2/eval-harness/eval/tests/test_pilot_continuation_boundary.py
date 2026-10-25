"""Specific D-061 control-file transition, in a wholly synthetic filesystem."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest

from communication_pruning.pilot_continuation_guard import (
    CONTROL_REL, CONTROL_ORIGINAL, R3_PLAN, check_original_files, checksum, save)
from communication_pruning.pilot_execution import PilotStop


class ControlTransitionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.old = {'next': {'id': 'Z42-PILOT', 'author_decision': 'D-059',
                             'plan': 'project/dsr/Z42-PILOT-PLAN.md'},
                    'design': {'sha256': 'a' * 64}}
        self.current = deepcopy(self.old)
        self.current['next'].update(author_decision='D-061', plan=R3_PLAN)
        for name, value in ((CONTROL_ORIGINAL, self.old), (CONTROL_REL, self.current),
                            (R3_PLAN, {'synthetic': True}), ('original-source.py', {'original': True})):
            save(self.root / name, value)
        self.entries = {CONTROL_REL: checksum(self.root / CONTROL_ORIGINAL),
                        'original-source.py': checksum(self.root / 'original-source.py')}
        self.current_files = {name: checksum(self.root / name) for name in (CONTROL_REL, CONTROL_ORIGINAL, R3_PLAN)}

    def test_one_explicit_transition_keeps_original_and_new_bound(self):
        check_original_files(self.root, self.entries, self.current_files)

    def test_changed_original_copy_or_unrelated_source_blocks(self):
        for name in (CONTROL_ORIGINAL, 'original-source.py', R3_PLAN, CONTROL_REL):
            path = self.root / name
            original = path.read_bytes()
            path.write_bytes(original + b' ')
            with self.assertRaises(PilotStop):
                check_original_files(self.root, self.entries, self.current_files)
            path.write_bytes(original)

    def test_resigned_wrong_authority_design_and_plan_block(self):
        for change in ({'author_decision': 'D-059'}, {'id': 'Z43'}, {'plan': 'unbound.md'}):
            current = deepcopy(self.current)
            current['next'].update(change)
            (self.root / CONTROL_REL).write_text(json.dumps(current))
            self.current_files[CONTROL_REL] = checksum(self.root / CONTROL_REL)
            with self.assertRaises(PilotStop):
                check_original_files(self.root, self.entries, self.current_files)
        current = deepcopy(self.current)
        current['design']['sha256'] = 'b' * 64
        (self.root / CONTROL_REL).write_text(json.dumps(current))
        self.current_files[CONTROL_REL] = checksum(self.root / CONTROL_REL)
        with self.assertRaises(PilotStop):
            check_original_files(self.root, self.entries, self.current_files)

    def test_missing_transition_binding_or_symlink_blocks(self):
        for name in (CONTROL_REL, CONTROL_ORIGINAL, R3_PLAN):
            current = dict(self.current_files)
            del current[name]
            with self.assertRaises(PilotStop):
                check_original_files(self.root, self.entries, current)
        original = self.root / CONTROL_ORIGINAL
        duplicate = self.root / 'duplicate.json'
        duplicate.write_bytes(original.read_bytes())
        original.unlink()
        original.symlink_to(duplicate)
        with self.assertRaises(PilotStop):
            check_original_files(self.root, self.entries, self.current_files)
