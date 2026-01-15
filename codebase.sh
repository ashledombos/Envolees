find . -type d \( -name .git -o -name __pycache__ \) -prune -o \
     -type f ! -path '*/.git/*' ! -path '*/__pycache__/*' \
            ! -name '.envi.secret*' ! -name '*.pyc' ! -name '*.pyo' \
            ! -name '*.txt' ! -name '*codebase.md' ! -name 'tous_*.txt' \
     -exec sh -c 'printf "\n%s\n────────────────────────────────────────────────────────────\n\n" "{}" && cat "{}" && printf "\n\n"' \; \
     > codebase.md
