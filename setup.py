from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = [
        line.strip() for line in f if line.strip() and not line.startswith("#")
    ]

setup(
    name="rathausrot",
    version="0.1.0",
    description="Kommunalpolitik-Bot für Matrix – automatische Analyse von Ratssitzungen",
    author="RathausRot Contributors",
    license="GPLv3",
    python_requires=">=3.11",
    packages=find_packages(),
    install_requires=install_requires,
    entry_points={
        "console_scripts": [
            "rathausrot=rathausrot.main:main",
        ],
    },
    classifiers=[
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
