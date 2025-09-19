from pathlib import Path
import re

path = Path('MainApp.py')
text = path.read_text(encoding='utf-8')
pattern = re.compile(r"\s{8}sec = m_insert.addMenu\(\"Sections\"\)\n.*?icons = m_insert.addMenu\(\"Icon \(inline SVG\)\"\)\n", re.S)
new_block = "        sec = m_insert.addMenu(\"Sections\")\n        self._add_action(sec, \"Hero (headline + CTA)\", lambda: self.insert_html(html_section_hero()))\n        self._add_action(sec, \"Feature highlights\", lambda: self.insert_html(html_section_features()))\n        self._add_action(sec, \"Split content (copy + image)\", lambda: self.insert_html(html_section_two_column()))\n        self._add_action(sec, \"Call-to-action\", lambda: self.insert_html(html_section_cta()))\n        self._add_action(sec, \"FAQ accordion\", lambda: self.insert_html(html_section_faq()))\n        self._add_action(sec, \"Pricing tiers\", lambda: self.insert_html(html_section_pricing()))\n\n        components = m_insert.addMenu(\"Components\")\n        self._add_action(components, \"Button row (3 actions)\", lambda: self.insert_html(html_component_button_row()))\n        self._add_action(components, \"Stats grid\", lambda: self.insert_html(html_component_stat_list()))\n        self._add_action(components, \"Testimonial card\", lambda: self.insert_html(html_component_testimonial()))\n\n        gfx = m_insert.addMenu(\"Graphics\")\n        self._add_action(gfx, \"Wave divider (top)\", lambda: self.insert_html(svg_wave(self.project.palette[\"surface\"], False)))\n        self._add_action(gfx, \"Wave divider (bottom)\", lambda: self.insert_html(svg_wave(self.project.palette[\"surface\"], True)))\n        self._add_action(gfx, \"Placeholder image\", self.insert_placeholder_dialog)\n\n        icons = m_insert.addMenu(\"Icon (inline SVG)\")\n"
text, count = pattern.subn(new_block, text, count=1)
if count != 1:
    raise SystemExit('Failed to update insert menu indentation')

path.write_text(text, encoding='utf-8')
