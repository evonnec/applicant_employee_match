#!/bin/bash -e

echo "Looking for pyenv"
if ! [ -x "$(command -v pyenv)" ]; then
    echo "Installing pyenv"
    curl https://pyenv.run | bash
else
    echo "pyenv is already installed"
fi

PYTHON_VERSION=`< .python-version`
echo "Installing Python $PYTHON_VERSION"
pyenv install --skip-existing "$PYTHON_VERSION"

echo "Setting up venv in $PWD/venv"
python3 -m venv venv

source venv/bin/activate

echo "Installing dependencies"
python3 -m pip install -r requirements.txt -r requirements-dev.txt

echo "Done! You will need to 'source venv/bin/activate'"
