===========================
Wildbook IA - wbia_whaleridgefindr
===========================

|Build| |Pypi| |ReadTheDocs|

whaleridgefindr Plug-in - Part of the WildMe / Wildbook IA Project.

A plug-in for using the containerized version of the `whaleridgefindr gray whale ID algorithm <https://github.com/haimeh/finFindR>`_.

Running the whaleridgefindr Container
------------------------------
This plugin assumes that:

1. You have separately started the whaleridgefindr container with the command: 

.. code:: bash

    docker run -p 8004:8004/tcp --name flukebook_whaleridgefindr --network flukebook haimeh/whaleridgefindr:latest

2. Your WBIA container also has the same network ("flukebook" above) defined for it.

Development Setup
-----------------

.. code:: bash

    ./run_developer_setup.sh
    
Code Style and Development Guidelines
-------------------------------------

Contributing
~~~~~~~~~~~~

It's recommended that you use ``pre-commit`` to ensure linting procedures are run
on any commit you make. (See also `pre-commit.com <https://pre-commit.com/>`_)

Reference `pre-commit's installation instructions <https://pre-commit.com/#install>`_ for software installation on your OS/platform. After you have the software installed, run ``pre-commit install`` on the command line. Now every time you commit to this project's code base the linter procedures will automatically run over the changed files.  To run pre-commit on files preemtively from the command line use:

.. code:: bash

    git add .
    pre-commit run

    # or

    pre-commit run --all-files

Brunette
~~~~~~~~

Our code base has been formatted by Brunette, which is a fork and more configurable version of Black (https://black.readthedocs.io/en/stable/).

Flake8
~~~~~~

Try to conform to PEP8.  You should set up your preferred editor to use flake8 as its Python linter, but pre-commit will ensure compliance before a git commit is completed.

To run flake8 from the command line use:

.. code:: bash

    flake8

This will use the flake8 configuration within ``setup.cfg``,
which ignores several errors and stylistic considerations.
See the ``setup.cfg`` file for a full and accurate listing of stylistic codes to ignore.

PyTest
~~~~~~

Our code uses Google-style documentation tests (doctests) that uses pytest and xdoctest to enable full support.  To run the tests from the command line use:

.. code:: bash

    pytest

.. |Build| image:: https://img.shields.io/github/workflow/status/WildMeOrg/wbia-plugin-whaleridgefindr/Build%20and%20upload%20to%20PyPI/main
    :target: https://github.com/WildMeOrg/wbia-plugin-whaleridgefindr/actions?query=branch%3Amain+workflow%3A%22Build+and+upload+to+PyPI%22
    :alt: Build and upload to PyPI (main)

.. |Pypi| image:: https://img.shields.io/pypi/v/wbia-whaleridgefindr.svg
   :target: https://pypi.python.org/pypi/wbia-whaleridgefindr
   :alt: Latest PyPI version

.. |ReadTheDocs| image:: https://readthedocs.org/projects/wbia-plugin-whaleridgefindr/badge/?version=latest
    :target: https://wbia-plugin-whaleridgefindr.readthedocs.io/en/latest/
    :alt: Documentation on ReadTheDocs
