# lambda-cli
CLI for managing [Lambda Labs](https://lambdalabs.com/service/gpu-cloud) instances.

## Installation
```bash
pip install lambda-cli
```

You may also install the package from source:
```bash
git clone https://github.com/gmittal/lambda-cli
cd lambda-cli
pip install .
```

## Usage

Authenticate with your email and password:

```shell
lambda auth
```

Create instances:

```shell
$ lambda up --instance_type=gpu.8x.v100
```

List existing instances:

```shell
$ lambda ls
ID                                IP               INSTANCE_TYPE  STATE
23d0a8af2e414762ab8a10d3841d9574  104.171.203.194  gpu.8x.v100    BOOTING
```

Terminate instances:

```shell
$ lambda rm 23d0a8af2e414762ab8a10d3841d9574
```

## License
MIT
