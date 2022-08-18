from setuptools import setup
from os import path
from io import open

here = path.abspath(path.dirname(__file__)) + '/'

with open(path.join(here, 'README.md'), encoding='utf-8') as f: long_description = f.read()

setup(
    name='lambda',
    version='1.0.0',
    description="Lambda Labs instance management",
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/gmittal/lambda-cli',
    author='Gautam Mittal',
    keywords='development',
    packages=["lambda"],
    # package_data={'lambda': [ 'insttypes.txt', 'prices.csv' ]},
    entry_points={ 'console_scripts': [ 'lambda=lambda:main'] },
    install_requires=[ 'fire', 'jinja2', 'pyppeteer' ],
)
