from __future__ import annotations

from hal import domain


def test_domain_package_exports_context_unit_semantics() -> None:
    assert hasattr(domain, "ContextUnit")
    assert hasattr(domain, "ContextUnitManifest")
    assert hasattr(domain, "SkillContextUnit")
    assert hasattr(domain, "ThreadContextUnit")
