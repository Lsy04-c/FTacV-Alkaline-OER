# Architecture validation artifacts

Scripts may overwrite generated JSON, CSV, and PNG files in this directory.
Each generated file must record the tested commit, input data, configuration,
random seed when applicable, and the command that produced it.

Markdown conclusions require manual review before commit. A failed diagnostic
remains valid evidence when its command, exit status, and error output are
recorded. Generated results must not be described as confirmed findings until
the corresponding tests and report review pass.
