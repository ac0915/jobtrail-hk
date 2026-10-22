"""Static checks for the owner provisioning safety controls."""
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/provision_owner.py'
MIGRATION = Path(__file__).resolve().parents[1] / 'db/migrations/005_owner_cutover.sql'


def test_provisioning_requires_explicit_mode():
    source = SCRIPT.read_text(encoding='utf-8')
    assert "parser.add_argument('--dry-run'" in source
    assert "parser.add_argument('--apply'" in source
    assert "args.dry_run == args.apply" in source
    assert "OWNER_EMAIL" in source


def test_provisioning_only_assigns_unowned_jobs():
    source = SCRIPT.read_text(encoding='utf-8')
    assert "WHERE user_id IS NULL" in source
    assert "UPDATE public.jobs" in source


def test_ownership_cutover_blocks_unowned_jobs():
    migration = MIGRATION.read_text(encoding='utf-8')
    assert "WHERE user_id IS NULL" in migration
    assert "ALTER COLUMN user_id SET NOT NULL" in migration
