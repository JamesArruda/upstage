# Comments from L. Starnes

> Delete this file before merge.

1. ~~It is "UPSTAGE" 122 times over 35 files. 1. In CONTRIBUTING.md you say "then install to your environment with `pip install -e ...`. You had them get mambaforge, but they never set up a conda environment. So, what environment are they installing into? Also, there is no environment.yml -- so does  the `mambaforge` stuff need to be removed?~~
1. ~~It looks like you pulled out all the `doit` stuff. I am happy either way -- I did want to make sure that you didn't think that the `doit` powered automation was incompatible in some way with OSS. IMO, as long as it works and is sufficiently documented then its all good. I'm not saying you need to add it back -- it is your call.~~
1. ~~If `doit` is dead then pull out the `doit` stuff in `pyproject.toml`.~~
1. ~~You may want to check out poetry. It works on your `pyproject.toml`. It automatically handles creating a lock file (that you put in source control). So instead of `pip install -e`, you would just do `poetry install`. You can install poetry with `curl -sSL https://install.python-poetry.org | python`.~~
1. ~~The Style Guide says you use Flake 8. You kind of do since the rules are in Ruff, but I would clarify that.~~
1. ~~In `STYLE_GUIDE.md`, I made a new section called `Linting` which was the first bit of the `Testing` section. I left the words the same but its all about flake8 but are not on the ruff train.~~
1. ~~In `STYLE_GUIDE.md`, you say~~
    ~~> Docstring example code tests are executed using [doctest](https://docs.python.org/3/library/doctest.html).~~

    ~~But, you are not using `doctest`. It does look like there is some test code in your doc strings so maybe you should be?~~
1. ~~Note how [RMT](https://github.com/gtri/rapid-modeling-tools/blob/master/LICENSE) says the license when you view the LICENSE? [Yours](https://github.com/JamesArruda/upstage/blob/main/LICENSE) does not. Can you try and make that work?~~
1. ~~It might be worth breaking out a separate `optional-dependencies` for linters/formatters (and not combining with pytest in `test`)~~
1. ~~In `.github/workflows/lint.yml`, the line `if: success() || failure()` needs tto be removed before merge. Debug only.~~
1. As of 7/19, running `ruff check --fix src` found 138 errors.
1. I experimented with enabling E501 (line-too-long) and changing the line length to 100. I fixed some of the findings. There are 41 left. NOTE: by setting line length to 100 `ruff format` changed a bunch of code to make lines longer.
1. I ran the following and got this error -- `no matches found: .[docs,test]`

    ```bash
    mamba create --name upstage python==3.11 pip
    python -m pip install --upgrade pip
    pip install -e .[docs,test]
    ```

    After some trial and error -- seems you need to put single quotes around `.[docs,test]`.
1. I noticed that `sphinx-apidoc` has as an option specific to GitHub, `--ext-githubpages` (<https://www.sphinx-doc.org/en/master/usage/extensions/githubpages.html>) -- just FYI.
1. In CI, you have things set to only run `pytest` when on `main` or when you have a PR targeted to `main`. You say that contributors should target `dev` so this means tests will not run for those PRs. The tests seem fast. Maybe just always run them?
1. Docs
    1. first page - why is `STAGE` in all caps? seems to be only word (except UPSTAGE) in all caps. (this is in README the same way)
1. This is probably a future thing... but you are going to need the ability for users to look at the docs for different versions of the tool. See:

    - <https://stackoverflow.com/questions/47643881/github-pages-maintaining-multiple-versions>
    - <https://pydata-sphinx-theme.readthedocs.io/en/stable/user_guide/version-dropdown.html>

    Note that this may be a place RTD excels <https://docs.readthedocs.io/en/stable/versions.html> (more -- pretty slick IMO -- <https://docs.readthedocs.io/en/stable/integrations.html>).

1. When you get ready for initial release, be sure to do a [GH release](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)
1. I would consider releasing as `0.1.0` rather than `1.0.0`. `1.0` is supposed to signify stability in your API (per https://semver.org/).
1. Given that you have your version in 2 places (`src/upstage/_version.py` and `pyproject.toml`) plus you probably need it in the README and in the docs, I recommend <https://github.com/callowayproject/bump-my-version>
