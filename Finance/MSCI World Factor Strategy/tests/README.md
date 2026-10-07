# Validation

Tests check account identities, date alignment, costs, financing, independent arithmetic, scenario/cohort ownership, unavailable-return states, evidence seals and report selections. The new common workflow also rejects changed or incomplete reference results before binding readers.

```sh
.venv/bin/python -m pytest -p no:cacheprovider
```

Passing unit tests is separate from the original-data integration replay. Follow[complete reconstruction](../REPRODUCE.md), then inspect its checks and newly rendered PDFs. The[verification record](../docs/VERIFICATION.md) states the actual platform/scope and remaining publication experiment. Tests and a second AI-assisted implementation are not independent human expert review.
