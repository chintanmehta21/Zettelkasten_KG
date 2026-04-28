# 3A.1 Add-zettels modal — Select-all + counter (manual verification)

**Surface:** `/home/rag` → 3-dot menu → "Add zettels"

## Visual checklist

- [ ] Header row appears at the top of the list with checkbox + "Select all visible" label and a teal counter `0 / N selected` on the right.
- [ ] Header row has the soft-teal `--accent-glow` background and a teal-muted bottom border. No purple/violet/lavender. No amber/gold.
- [ ] Header row sticks to the top of the scrollable list while scrolling through long lists.

## Behavioral checklist

- [ ] Clicking "Select all visible" with no rows selected → every selectable (non-member, currently-visible) row becomes checked, counter shows `N / N selected`, footer button shows "Add N zettels".
- [ ] Clicking again → all clear, counter `0 / N`, footer button "Add 0 zettels" disabled.
- [ ] Manually checking one row → header checkbox enters indeterminate state, counter increments to `1 / N`.
- [ ] Manually checking ALL rows individually → header checkbox becomes fully checked, counter `N / N`.
- [ ] Typing in the search box narrows the list AND the counter denominator updates to the new visible-selectable count; selections outside the filter persist (footer count unchanged).
- [ ] Already-member rows are dimmed and never counted in the denominator, never selected by Select-all.
- [ ] When `selectableCount === 0` (everything already added), the header checkbox is disabled.

## Cross-checks

- [ ] No regression on existing per-row toggle / footer button / submit flow.
- [ ] Esc still closes the modal.
- [ ] Counter uses tabular-nums so the digits don't jitter.
