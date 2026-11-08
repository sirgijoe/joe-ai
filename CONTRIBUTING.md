# Contributing to Joe

Thanks for wanting to help. Joe is free software under the GPL, made to make people's lives a little easier.

## Ways to help

- **Report a bug or suggest an idea:** [open an issue](https://github.com/sirgijoe/joe-ai/issues/new/choose). Screenshots and steps to reproduce help a lot.
- **Improve the docs:** typo fixes and clearer wording are always welcome.
- **Write code:** for anything bigger than a small fix, open an issue first so we can agree on the approach before you spend time on it.

## Working on the code

- Install Python 3.11.4+ and run `python -m joeai` from the repo folder (see *What you need* in the README).
- Joe's core is Python's standard library only. Please don't add required third-party packages; optional ones belong in add-ons.
- Before sending a pull request, run the tests: `python -m pytest -q tests`.
- Keep changes focused, one fix or feature per pull request, and describe what you changed and how you tested it.
- Write messages and text in the app in plain, friendly language. Many users aren't technical.

## License

By contributing, you agree your work is released under the same license as the rest of Joe (see [LICENSE](LICENSE)).

Please follow the [code of conduct](CODE_OF_CONDUCT.md).
