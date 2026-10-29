import random

import pytest

from englishwords.print_layout import column_grid, grid_height, plan_pages


def test_column_grid_balances_even_three_columns():
    assert column_grid([1, 2, 3, 4], 2) == [[1, 3], [2, 4]]
    assert column_grid(list(range(1, 8)), 3) == [[1, 4, 6], [2, 5, 7], [3, None, None]]


@pytest.mark.parametrize('columns', [1, 2, 3])
def test_variable_heights_fit_shared_rows_and_keep_group_order(columns):
    rng = random.Random(20261029)
    groups = [list(range(1, 38)), list(range(38, 179)), list(range(179, 214))]
    heights = {n: rng.choice([20, 25, 40, 65, 100]) for group in groups for n in group}
    pages = plan_pages(groups, columns, heights, [42, 60, 42], 800, 135)
    actual = [[] for _ in groups]
    for page_index, chunks in enumerate(pages):
        used = 135 if page_index == 0 else 0
        for group_index, grid in chunks:
            selected = [row[column] for column in range(columns) for row in grid
                        if row[column] is not None]
            actual[group_index].extend(selected)
            used += [42, 60, 42][group_index] + grid_height(selected, columns, heights) + 8
            counts = [sum(row[c] is not None for row in grid) for c in range(columns)]
            assert max(counts) - min(counts) <= 1
        assert used <= 800
    assert actual == groups


def test_oversized_single_entry_is_rejected_instead_of_clipped():
    with pytest.raises(ValueError, match='超过 A4'):
        plan_pages([[1]], 2, {1: 1000}, [42], 800, 135)


def test_group_breaks_keep_groups_on_separate_pages():
    pages = plan_pages([[1, 2], [3, 4]], 2, dict.fromkeys(range(1, 5), 20),
                       [40, 40], 800, 100, break_sections=True)
    assert len(pages) == 2
    assert [chunk[0] for chunk in pages[0]] == [0]
    assert [chunk[0] for chunk in pages[1]] == [1]
