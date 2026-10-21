"""Pipeline"""

import data_cleaning
import pair_feature
import rules_paired
import time_grid
import window_feature

RUN_CHECK = False
YEARS = [2017, 2018, 2019, 2020]
STEPS = [
    # data_cleaning, # slow
    time_grid,
    pair_feature,
    window_feature,
    rules_paired,
]


def main() -> None:
    for step in STEPS:
        step.RUN_CHECK = RUN_CHECK
        if step != data_cleaning:
            step.YEARS = YEARS
        print(step.__name__)
        step.main()


if __name__ == "__main__":
    main()
