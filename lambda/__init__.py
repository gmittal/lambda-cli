import fire
from .lambda_api import *


def main():
    controller = Lambda()
    fire.Fire(controller)


if __name__ == '__main__': main()
