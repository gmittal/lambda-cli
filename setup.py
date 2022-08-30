from setuptools import setup
from os import path
from io import open

here = path.abspath(path.dirname(__file__)) + '/'

with open(path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='lambda-cli',
    version='1.0.1',
    description="Lambda Labs instance management",
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/gmittal/lambda-cli',
    author='Gautam Mittal',
    keywords='development',
    packages=["lambda_labs"],
    requires_python='>=3.6',
    package_data={'lambda_labs': ['catalog.csv']},
    entry_points={'console_scripts': ['lambda=lambda_labs:main']},
    install_requires=[
        'colorama', 'fire', 'jinja2', 'pandas', 'pendulum', 'petname',
        'prettytable', 'pyppeteer'
    ],
)
