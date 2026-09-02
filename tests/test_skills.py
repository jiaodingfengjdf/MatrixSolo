from __future__ import annotations

import io
import zipfile

import pytest

from matrixsolo.admin.models import AgentProfile, AgentRoleKey, PromptSkill, PromptSkillCreate
from matrixsolo.admin.store import ProfileStore
from matrixsolo.feishu.chat import IMAGE_ASK, is_install_intent
from matrixsolo.skills.package import parse_skill_bytes, parse_skill_md
from matrixsolo.skills.runtime import SkillRuntime, can_image_gen, html_to_text, parse_skill_call, strip_think


def test_strip_think_and_skill_call():
    raw = "<think>**Planning**</think>\n先拉热榜。\n```json\n{\"skill\":\"hot_radar\"}\n```"
    cleaned = strip_think(raw)
    assert "<think>" not in cleaned
    leftover = strip_think("<think>**Planning poster direction with mood check**\n\n行，先定情绪。")
    assert "<think>" not in leftover
    assert "先定情绪" in leftover
    call = parse_skill_call(raw)
    assert call and call["skill"] == "hot_radar"


def test_parse_skill_md_and_zip():
    md = """---
name: hot-radar-notes
description: 影视热榜阅读口径
---

# 热榜
优先看切口，不看排名本身。
"""
    pack = parse_skill_md(md)
    assert pack.name == "hot-radar-notes"
    assert "切口" in pack.content

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hot-radar-notes/SKILL.md", md)
    parsed = parse_skill_bytes(buf.getvalue(), "pack.zip")
    assert parsed.name == "hot-radar-notes"


def test_html_to_text_skips_script():
    text = html_to_text("<html><script>evil()</script><body><h1>盗梦空间</h1></body></html>")
    assert "盗梦空间" in text
    assert "evil" not in text


def test_install_intent():
    assert is_install_intent("https://example.com/SKILL.md")
    assert is_install_intent("帮我安装这个技能 https://x.com/a.zip")
    assert is_install_intent("你好", "guide.md")
    assert not is_install_intent("看看 https://movie.douban.com/chart")


def test_store_install_skill(tmp_path, monkeypatch):
    monkeypatch.setenv("MATRIXSOLO_DATA_DIR", str(tmp_path))
    store = ProfileStore(path=tmp_path / "agent_profiles.json")
    profile = store.get("strategy")
    assert any(t.key == "web_fetch" and t.enabled for t in profile.tools)
    updated = store.add_skill(
        "script",
        PromptSkillCreate(name="hook", content="前三秒", source="upload", origin="hook.md"),
    )
    assert any(s.name == "hook" and s.source == "upload" for s in updated.skills)


def test_image_ask_and_can_image_gen():
    assert IMAGE_ASK.search("帮我生图一张赛博封面")
    assert IMAGE_ASK.search("出一张海报")
    assert IMAGE_ASK.search("画一张竖版封面")
    assert not IMAGE_ASK.search("封面安全区怎么留")

    pack = AgentProfile(
        role=AgentRoleKey.VISUAL,
        title="视觉",
        tools=[],
        skills=[
            PromptSkill(
                name="grsai-image-gen",
                content="python scripts/generate.py",
                origin="image-gen.zip",
            )
        ],
    )
    assert can_image_gen(pack)

    disabled = AgentProfile(role=AgentRoleKey.VISUAL, title="视觉", enabled=False)
    assert not can_image_gen(disabled)


def test_extract_local_markdown_image(tmp_path, monkeypatch):
    from matrixsolo.feishu.chat import _extract_local_images, _resolve_image_file

    covers = tmp_path / "data" / "exports" / "covers"
    covers.mkdir(parents=True)
    png = covers / "grsai_041b659481.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 20)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MATRIXSOLO_DATA_DIR", str(tmp_path / "data"))
    from matrixsolo.config import get_settings

    get_settings.cache_clear()
    text, found = _extract_local_images(
        "行，图已经落地了。\n![海报](data\\exports\\covers\\grsai_041b659481.png)\n再来一版？"
    )
    assert "海报" not in text or "![" not in text
    assert found and found[0].endswith("grsai_041b659481.png")
    assert _resolve_image_file("grsai_041b659481.png")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_image_gen_skipped_in_pytest():
    out = await SkillRuntime().image_gen("a cinematic film poster")
    assert out["ok"] is True
    assert out["paths"] == []
