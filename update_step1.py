from pathlib import Path
import re
import textwrap

path = Path('MainApp.py')
text = path.read_text(encoding='utf-8')

sentinel = "CSS_HELPERS_SENTINEL = \"/* === WEBINEER CSS HELPERS (DO NOT DUPLICATE) === */\""
if "TEMPLATE_EXTRA_SENTINEL" not in text:
    text = text.replace(sentinel, sentinel + '\nTEMPLATE_EXTRA_SENTINEL = "/* === WEBINEER TEMPLATE EXTRA CSS === */"')

text = text.replace("extra_css: Optional[str] = None", "extra_css: str = \"\"")

pattern_templates = re.compile(r"\s*PROJECT_TEMPLATES: Dict\\[str, TemplateSpec] = \{.*?DEFAULT_TEMPLATE_KEY = \"starter\"", re.S)
replacement = textwrap.dedent('''
PROJECT_TEMPLATES: Dict[str, TemplateSpec] = {
    "starter": TemplateSpec(
        name="Starter landing",
        description="Versatile marketing layout with hero, features, and testimonial.",
        pages=[
            ("index.html", "Home", DEFAULT_INDEX_HTML),
        ],
        extra_css=STARTER_TEMPLATE_CSS,
        include_helpers=True,
    ),
    "portfolio": TemplateSpec(
        name="Portfolio spotlight",
        description="Introduce yourself, showcase projects, and invite conversations.",
        pages=[
            ("index.html", "Home", PORTFOLIO_INDEX_HTML),
            ("projects.html", "Projects", PORTFOLIO_PROJECTS_HTML),
        ],
        palette=dict(primary="#7c3aed", surface="#fcfbff", text="#1f2933"),
        fonts=dict(
            heading="Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Arial",
            body="Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Arial",
        ),
        extra_css=PORTFOLIO_TEMPLATE_CSS,
        include_helpers=True,
    ),
    "resource": TemplateSpec(
        name="Resource hub",
        description="Organize guides, troubleshooting steps, and FAQs with ease.",
        pages=[
            ("index.html", "Overview", RESOURCE_INDEX_HTML),
            ("guide.html", "Quick start guide", RESOURCE_GUIDE_HTML),
        ],
        palette=dict(primary="#0ea5e9", surface="#f5faff", text="#0f172a"),
        fonts=dict(
            heading="Segoe UI, system-ui, -apple-system, Roboto, Ubuntu, 'Helvetica Neue', Arial",
            body="Segoe UI, system-ui, -apple-system, Roboto, Ubuntu, 'Helvetica Neue', Arial",
        ),
        extra_css=RESOURCE_TEMPLATE_CSS,
        include_helpers=True,
    ),
}
DEFAULT_TEMPLATE_KEY = "starter"
''')

if "STARTER_TEMPLATE_CSS" not in text:
    text = text.replace(
        "DEFAULT_INDEX_HTML = \"\"\"\\\n",
        "DEFAULT_INDEX_HTML = \"\"\"\\\n" + "",
    )

if "STARTER_TEMPLATE_CSS" not in text:
    text = text.replace(
        "DEFAULT_INDEX_HTML = \"\"\"\\\n" + "",
        "DEFAULT_INDEX_HTML = \"\"\"\\\n" + "",
    )

if "STARTER_TEMPLATE_CSS" not in text:
    block = textwrap.dedent('''
STARTER_TEMPLATE_CSS = """/* Template: Starter Landing */
.hero {
  text-align: center;
  background: color-mix(in srgb, var(--color-primary) 8%, var(--color-surface));
  box-shadow: 0 16px 48px rgba(15, 23, 42, .12);
}
.hero-actions .btn {
  min-width: 11rem;
}
.feature-grid .card {
  transition: transform .18s ease, box-shadow .18s ease;
}
.feature-grid .card:hover {
  transform: translateY(-4px);
  box-shadow: 0 22px 45px rgba(15, 23, 42, .18);
}
.split .card {
  background: var(--color-surface);
}
"""

PORTFOLIO_INDEX_HTML = """\
<section class="hero portfolio-hero">
  <div class="hero-inner">
    <p class="eyebrow">Product designer</p>
    <h2>Hi, I'm Riley Stone.</h2>
    <p class="hero-lede">I help SaaS teams craft human-centered onboarding and growth experiences.</p>
    <div class="hero-actions">
      <a class="btn btn-primary btn-lg" href="#projects">View projects</a>
      <a class="btn btn-soft btn-lg" href="projects.html">Case studies</a>
    </div>
  </div>
  <div class="hero-image">
    <div class="profile-placeholder">Add your portrait</div>
  </div>
</section>
<section id="projects" class="section">
  <div class="stack text-center max-w-lg">
    <p class="eyebrow">Selected work</p>
    <h3>Showcase impactful projects</h3>
    <p class="text-muted">Swap these cards with your own case studies and highlight outcomes.</p>
  </div>
  <div class="portfolio-grid">
    <article class="project-card stack">
      <h4>Checkout flow redesign</h4>
      <p class="text-muted">Increased conversions 18% for a developer tools platform.</p>
      <a class="btn btn-ghost" href="projects.html#checkout">Read the case study</a>
    </article>
    <article class="project-card stack">
      <h4>Analytics dashboard</h4>
      <p class="text-muted">Delivered an insights hub the whole team can trust.</p>
      <a class="btn btn-ghost" href="projects.html#dashboard">View highlights</a>
    </article>
    <article class="project-card stack">
      <h4>Onboarding refresh</h4>
      <p class="text-muted">Cut time-to-value in half with contextual walkthroughs.</p>
      <a class="btn btn-ghost" href="projects.html#onboarding">See outcomes</a>
    </article>
  </div>
</section>
<section class="section-alt">
  <div class="timeline">
    <article class="timeline-item">
      <h4>Current</h4>
      <p class="text-muted">Design lead at BrightStack, shaping onboarding for 2M users.</p>
    </article>
    <article class="timeline-item">
      <h4>Previously</h4>
      <p class="text-muted">Product designer at Northwind, focused on growth experimentation.</p>
    </article>
    <article class="timeline-item">
      <h4>Tools</h4>
      <p class="text-muted">Figma, FigJam, Maze, Miro, Notion, Webflow, HTML/CSS.</p>
    </article>
  </div>
</section>
<section class="section">
  <div class="contact-card stack text-center">
    <h3>Let's build something great</h3>
    <p class="text-muted">Share a challenge or say hello at <a href="mailto:riley@example.com">riley@example.com</a>.</p>
    <div class="hero-actions">
      <a class="btn btn-primary btn-lg" href="mailto:riley@example.com">Book a call</a>
      <a class="btn btn-outline btn-lg" href="projects.html">See full portfolio</a>
    </div>
  </div>
</section>
"""

PORTFOLIO_PROJECTS_HTML = """\
<section class="section container-narrow" id="checkout">
  <h2>Selected case studies</h2>
  <article class="case-study stack">
    <h3>Checkout flow redesign</h3>
    <p class="text-muted">A five-week sprint to simplify purchasing for a developer tools platform.</p>
    <div class="stack">
      <h4>Outcome</h4>
      <ul class="list-check">
        <li>18% increase in conversions</li>
        <li>Reduced time-to-purchase by 42 seconds</li>
        <li>Streamlined plan selection for teams</li>
      </ul>
    </div>
  </article>
  <hr class="divider">
  <article class="case-study stack" id="dashboard">
    <h3>Analytics dashboard</h3>
    <p class="text-muted">Turning dense data into actionable insights for customer success teams.</p>
    <p>Introduce saved views, smarter defaults, and contextual glossary tips to keep teams aligned.</p>
  </article>
  <hr class="divider">
  <article class="case-study stack" id="onboarding">
    <h3>Onboarding refresh</h3>
    <p class="text-muted">Contextual in-app education that cut time-to-value in half.</p>
    <p>Add your own screenshots, quotes, and learnings here.</p>
  </article>
</section>
"""

PORTFOLIO_TEMPLATE_CSS = """/* Template: Portfolio Spotlight */
.portfolio-hero {
  display: grid;
  gap: 2.5rem;
  padding-block: 3.5rem;
}
.hero-inner {
  display: grid;
  gap: 1rem;
}
.hero-image {
  display: flex;
  align-items: center;
  justify-content: center;
}
.profile-placeholder {
  width: 220px;
  height: 220px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--color-primary) 18%, var(--color-surface));
  color: var(--color-primary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  letter-spacing: .05em;
  text-transform: uppercase;
}
.portfolio-grid {
  margin-top: 2.5rem;
}
.project-card {
  border-radius: var(--radius);
  border: 1px solid rgba(15, 23, 42, .08);
  padding: 1.5rem;
  background: var(--color-surface);
  box-shadow: 0 18px 50px rgba(15, 23, 42, .1);
}
.timeline-item {
  background: var(--color-surface);
  padding: 1.5rem 1.75rem;
  border-radius: var(--radius);
  box-shadow: 0 16px 40px rgba(15, 23, 42, .12);
}
.contact-card {
  padding: 2.5rem;
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--color-primary) 12%, var(--color-surface));
  box-shadow: 0 20px 48px rgba(15, 23, 42, .16);
}
@media (min-width: 840px) {
  .portfolio-hero {
    grid-template-columns: 3fr 2fr;
    align-items: center;
  }
}
"""

RESOURCE_INDEX_HTML = """\
<section class="hero docs-hero">
  <h2>Create a helpful resource hub</h2>
  <p class="hero-lede">Share product guides, onboarding steps, and FAQs with a clean, readable layout.</p>
  <div class="hero-actions">
    <a class="btn btn-primary btn-lg" href="#articles">Browse guides</a>
    <a class="btn btn-soft btn-lg" href="guide.html">Read the quick start</a>
  </div>
</section>
<section id="articles" class="section">
  <div class="docs-grid">
    <article class="doc-card stack">
      <h3>Getting started</h3>
      <p class="text-muted">Introduce your product and explain what to expect.</p>
      <a class="btn btn-outline" href="guide.html#basics">View outline</a>
    </article>
    <article class="doc-card stack">
      <h3>Troubleshooting</h3>
      <p class="text-muted">List common issues with quick fixes your users can try.</p>
      <a class="btn btn-outline" href="guide.html#faq">Jump to FAQs</a>
    </article>
    <article class="doc-card stack">
      <h3>Release notes</h3>
      <p class="text-muted">Keep your audience updated with the latest improvements.</p>
      <a class="btn btn-outline" href="#">Add a changelog</a>
    </article>
  </div>
</section>
<section class="section-alt">
  <div class="split">
    <div class="card stack">
      <h3>Keep things organized</h3>
      <p class="text-muted">Group related pages, surface next steps, and cross-link key resources.</p>
      <ul class="list-inline">
        <li>Callout tips</li>
        <li>Step-by-step tasks</li>
        <li>Release updates</li>
      </ul>
    </div>
    <div class="card stack">
      <h3>Share quick answers</h3>
      <details class="faq">
        <summary>How do I add a new page?</summary>
        <p>Use the Pages panel to add one, rename it, and start editing the HTML.</p>
      </details>
      <details class="faq">
        <summary>Can I paste my own CSS?</summary>
        <p>Yes&mdash;drop it into the Styles tab or use the Design tab to generate a theme first.</p>
      </details>
    </div>
  </div>
</section>
"""

RESOURCE_GUIDE_HTML = """\
<section class="section container-narrow" id="basics">
  <h2>Quick start guide</h2>
  <p class="text-muted">Use this outline to document a process or product quickly.</p>
  <ol class="stepper">
    <li>
      <h3>Explain the goal</h3>
      <p>Start with a short description of what someone will achieve and why it matters.</p>
    </li>
    <li>
      <h3>List the steps</h3>
      <p>Break the process into clear, numbered steps. Screenshots help readers stay oriented.</p>
    </li>
    <li>
      <h3>Highlight best practices</h3>
      <p>Call out gotchas, shortcuts, or recommended tools to stay on track.</p>
    </li>
  </ol>
  <aside class="callout"><strong>Tip:</strong> Link to supporting docs or video tutorials so readers can dive deeper.</aside>
  <section class="section-tight" id="faq">
    <h3>FAQs</h3>
    <ul class="list-check">
      <li>How do I share this page? &mdash; Export and upload it to your static host.</li>
      <li>Can I add more sections? &mdash; Duplicate the markup and tailor it to your product.</li>
      <li>Where do I edit styles? &mdash; Use the Styles tab or the Design tab for theme tweaks.</li>
    </ul>
  </section>
</section>
"""

RESOURCE_TEMPLATE_CSS = """/* Template: Resource Hub */
.docs-hero {
  text-align: center;
  padding-block: 3rem;
  background: color-mix(in srgb, var(--color-primary) 6%, var(--color-surface));
  box-shadow: 0 18px 40px rgba(15, 23, 42, .12);
}
.docs-grid {
  margin-top: 2.5rem;
}
.doc-card {
  border-radius: var(--radius);
  border: 1px solid rgba(15, 23, 42, .08);
  padding: 1.5rem;
  background: var(--color-surface);
  box-shadow: 0 16px 45px rgba(15, 23, 42, .1);
}
.callout {
  margin-top: 2.5rem;
}
.faq summary {
  font-weight: 600;
}
"""
''')
    marker = "# ---------------------- Data Model & Persistence ----------------------"
    if marker not in text:
        raise SystemExit('Data model marker missing')
    text = text.replace(marker, block + "\n\n" + marker, 1)

text, count = pattern_templates.subn(replacement, text, count=1)
if count != 1:
    raise SystemExit('Failed to replace PROJECT_TEMPLATES block')

text = text.replace("class='muted", "class='text-muted")

path.write_text(text, encoding='utf-8')
