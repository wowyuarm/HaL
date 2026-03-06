from __future__ import annotations

from hal.core.context.thread_mentions import detect_thread_mentions


def test_detect_thread_mentions_matches_slug_and_title_tokens() -> None:
    registry = [
        {
            "slug": "github-actions",
            "name": "GitHub Actions",
            "status": "active",
            "description": "workflow work",
            "state_path": "threads/github-actions/STATE.md",
        }
    ]

    assert detect_thread_mentions("Actions that one, continue it", registry) == {"github-actions"}


def test_detect_thread_mentions_ignores_ambiguous_shared_tokens() -> None:
    registry = [
        {
            "slug": "hal-architecture",
            "name": "HaL Architecture",
            "status": "active",
            "description": "kernel work",
            "state_path": "threads/hal-architecture/STATE.md",
        },
        {
            "slug": "blog-architecture",
            "name": "Blog Architecture",
            "status": "active",
            "description": "site work",
            "state_path": "threads/blog-architecture/STATE.md",
        },
    ]

    assert detect_thread_mentions("architecture 那个继续", registry) == set()


def test_detect_thread_mentions_supports_cjk_thread_names() -> None:
    registry = [
        {
            "slug": "hal-context-system",
            "name": "上下文系统",
            "status": "active",
            "description": "kernel work",
            "state_path": "threads/hal-context-system/STATE.md",
        }
    ]

    assert detect_thread_mentions("上下文系统那条线继续推进", registry) == {"hal-context-system"}
