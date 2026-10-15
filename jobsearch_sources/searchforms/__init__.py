"""Site-by-site, versioned search-form strategies for web-page job sites.

See ``base.py`` for the design (Strategy pattern + versioned registry),
``yahoo.py`` for a concrete site, ``recipe.py`` for declarative strategies,
``registry.py`` for lookup/resolution and ``runner.py`` for execution.
``service.py`` holds the operations the dashboards and CLI call.
"""

from .base import FIELD_KINDS, FormChanged, FormField, SearchFormStrategy, css_string, host_matches, map_criteria
from .learn import LearnedForm, learn_form, learned_results
from .recipe import RecipeStrategy, expand_steps, placeholders_in
from .registry import (
    Resolution,
    all_strategies,
    browser_plan,
    candidates,
    configured_strategy,
    families,
    for_url,
    get,
    learned_versions,
    next_learned_version,
    register,
    resolve,
    resolve_key,
    versions_of,
)
from .runner import FormRun, ensure_matched, run_form
from .service import Detection, FormTest, detect, form_block, form_site_options, mark_validated, site_with_criteria, test_form, validation_status, with_learned

__all__ = [
    "FIELD_KINDS", "FormChanged", "FormField", "SearchFormStrategy", "css_string", "host_matches", "map_criteria",
    "LearnedForm", "learn_form", "learned_results",
    "RecipeStrategy", "expand_steps", "placeholders_in",
    "Resolution", "all_strategies", "browser_plan", "candidates", "configured_strategy", "families", "for_url", "get",
    "learned_versions", "next_learned_version", "register", "resolve", "resolve_key", "versions_of",
    "FormRun", "ensure_matched", "run_form",
    "Detection", "FormTest", "detect", "form_block", "form_site_options", "mark_validated", "site_with_criteria", "test_form", "validation_status", "with_learned",
]
