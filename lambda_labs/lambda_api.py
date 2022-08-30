import asyncio
import getpass
import json
import os
import pathlib

import colorama
import jinja2
import pandas
import pendulum
import petname
import prettytable

from pyppeteer import launch

Fore = colorama.Fore
Style = colorama.Style

LOGIN_URL = 'https://lambdalabs.com/cloud/login'
DASHBOARD_URL = 'https://lambdalabs.com/cloud/dashboard/instances'
CREDENTIALS_PATH = '~/.lambda/credentials'
SESSION_COOKIE_PATH = '~/.lambda/session'
LOCAL_METADATA_PATH = '~/.lambda/metadata'
here = pathlib.Path(os.path.abspath(os.path.dirname(__file__)))


def readable_time_duration(start, end=None):
    """Human readable time duration from timestamps.

    https://github.com/skypilot-org/skypilot/blob/master/sky/utils/log_utils.py#L70

    Args:
        start: Start timestamp.
        end: End timestamp. If None, current time is used.
    Returns:
        Human readable time duration. e.g. "1 hour ago", "2 minutes ago", etc.
    """
    # start < 0 means that the starting time is not specified yet.
    if start is None or start < 0:
        return '-'
    if end is not None:
        end = pendulum.from_timestamp(end)
    start_time = pendulum.from_timestamp(start)
    duration = start_time.diff(end)
    diff = start_time.diff_for_humans(end)
    if duration.in_seconds() < 1:
        diff = '< 1 second'
    diff = diff.replace('second', 'sec')
    diff = diff.replace('minute', 'min')
    diff = diff.replace('hour', 'hr')

    return diff


async def start_session(credentials):
    browser = await launch(headless=True,
                           handleSIGINT=False,
                           handleSIGTERM=False,
                           handleSIGHUP=False)
    page = await browser.newPage()
    await page.emulateMedia('screen')
    await auth(page,
               email=credentials['email'],
               password=credentials['password'])
    return browser, page


async def auth(page, *, email=None, password=None):
    # set session cookie
    session_cookie_path = os.path.expanduser(SESSION_COOKIE_PATH)
    await page.goto(DASHBOARD_URL)
    if os.path.exists(session_cookie_path):
        with open(session_cookie_path, 'r') as f:
            cookies = json.load(f)
        await page.setCookie(cookies)
        await page.goto(DASHBOARD_URL)

    # login if needed (cookie expiration or first time)
    redirect_login = await page.evaluate('''() => {
        return document.querySelector('#password-input') !== null;
    }''')
    if redirect_login:
        print('Logging in...')
        await page.goto(LOGIN_URL)
        await page.type('#email-input', email)
        await page.type('#password-input', password)
        await page.click('.blue')  # submission button
        await page.screenshot(
            {'path': os.path.expanduser('~/.lambda/debug_login.png')})
        await page.goto(DASHBOARD_URL)

    # show dashboard login
    await page.screenshot(
        {'path': os.path.expanduser('~/.lambda/debug_list.png')})

    # grab session cookie
    client = await page.target.createCDPSession()
    cookies = (await client.send('Network.getAllCookies'))['cookies']
    for cookie in cookies:
        if cookie['name'] == 'sessionid':
            with open(session_cookie_path, 'w') as f:
                f.write(json.dumps(cookie))
            break


async def get_ssh_keys(page):
    await page.goto('https://lambdalabs.com/cloud/ssh-keys')
    key_data = await page.evaluate('''() => {
        return document.querySelector("#dashboard-container")
                       .getAttribute('ng-init');
    }''')
    key_data = (key_data.encode('latin1').decode('unicode-escape').encode(
        'latin1').decode('utf-8'))
    key_list = json.loads(key_data.split("', \'")[-1][:-2])
    return key_list


def display_key_list(key_list):
    if len(key_list) == 0:
        print('No existing keys.')
        return

    table = prettytable.PrettyTable(
        align='l',
        border=False,
        field_names=['ID', 'NAME', 'CREATED', 'PUB_KEY'])
    table.left_padding_width = 0
    table.right_padding_width = 2
    for key in key_list:
        table.add_row([
            key['id'], key['name'],
            readable_time_duration(key['created']), key['key'][:20] + '...'
        ])
    print(table)


async def list_ssh_keys(credentials, verbose=False):
    browser, page = await start_session(credentials)
    key_list = await get_ssh_keys(page)
    if verbose:
        display_key_list(key_list)
    await browser.close()
    return key_list


async def add_ssh_key(credentials, *, key, name=None, verbose=False):
    if name is None:
        name = petname.Generate()

    browser, page = await start_session(credentials)
    await page.goto('https://lambdalabs.com/cloud/ssh-keys')

    codegen = jinja2.Template('''() => {
        var xhr = new XMLHttpRequest();
        xhr.open("POST", "https://lambdalabs.com/api/cloud/keypairs", false);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.send(JSON.stringify({name: "{{name}}",
                                 public_key: "{{public_key}}"}));
        return JSON.parse(xhr.responseText);
    }''')
    response = await page.evaluate(codegen.render(name=name, public_key=key))
    req_error = response['error']

    if req_error is None:
        if len(response['data']) == 1:
            api_error = response['data'][0].get('err', None)
            if api_error is not None:
                if verbose:
                    print(f'Error: {api_error}')
                else:
                    await browser.close()
                    raise LambdaError(api_error)
                await browser.close()
                return None

        key_page = await browser.newPage()
        key_list = await get_ssh_keys(key_page)
        if verbose:
            display_key_list(key_list)
        await browser.close()
        for key_entry in key_list:
            if key_entry['name'] == name and key_entry['key'] == key:
                return key_entry
        return None

    else:
        if verbose:
            print(f'Error: {req_error}')
        else:
            await browser.close()
            raise LambdaError(req_error)
        await browser.close()
        return None


async def get_instances(page):
    await page.goto('https://lambdalabs.com/api/cloud/instances')
    instance_list = await page.evaluate('''() => {
        return JSON.parse(document.body.innerText);
    }''')
    return instance_list


def display_instance_list(instance_list):
    if len(instance_list['data']) == 0:
        print('No existing instances.')
        return

    table = prettytable.PrettyTable(
        align='l',
        border=False,
        field_names=['ID', 'IP', 'INSTANCE_TYPE', 'STATE'])
    table.left_padding_width = 0
    table.right_padding_width = 2
    for instance in instance_list['data']:
        instance_state = instance['state'].upper()
        if instance_state == 'CONTACTABLE':
            instance_state = 'RUNNING'
        table.add_row([
            instance['id'], instance['ipv4'], instance['ttype'], instance_state
        ])
    print(table)


async def list_instances(credentials, verbose=False):
    browser, page = await start_session(credentials)
    instance_list = await get_instances(page)
    if verbose:
        display_instance_list(instance_list)
    await browser.close()
    return instance_list


async def provision(credentials,
                    *,
                    instance_type,
                    region='us-tx-1',
                    count=1,
                    ssh_key_id=None,
                    verbose=False):
    browser, page = await start_session(credentials)

    if ssh_key_id is None:
        key_page = await browser.newPage()
        key_list = await get_ssh_keys(key_page)
        if len(key_list) == 0:
            raise LambdaError('No SSH keys found.')
        default_key = key_list[0]
        key_name = default_key['name']
        ssh_key_id = default_key['id']
        if verbose:
            print(f'Defaulting to first key \'{key_name}\' ({ssh_key_id})')

    codegen = jinja2.Template('''() => {
        var xhr = new XMLHttpRequest();
        xhr.open("POST",
                 "https://lambdalabs.com/api/cloud/instances-rpc",
                 false);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.send(JSON.stringify({
            method: "launch",
            params: {ttype: "{{instance_type}}",
                    quantity: {{count}},
                    region: "{{region}}",
                    public_key_id: "{{key_id}}",
                    filesystem_id: null}
        }));
        return JSON.parse(xhr.responseText);
    }''')
    response = await page.evaluate(
        codegen.render(instance_type=instance_type,
                       key_id=ssh_key_id,
                       count=count,
                       region=region))
    req_error = response['error']
    instance_list = None
    if req_error is None:
        if len(response['data']) > 0:
            api_error = response['data'][0].get('err', None)
            if api_error is not None:
                if verbose:
                    print(f'Error: {api_error}')
                else:
                    await browser.close()
                    raise LambdaError(api_error)
                await browser.close()
                return None

        instance_page = await browser.newPage()
        instance_list = await get_instances(instance_page)
        if verbose:
            display_instance_list(instance_list)
    else:
        if verbose:
            print(f'Error: {req_error}')
        else:
            await browser.close()
            raise LambdaError(req_error)

    await browser.close()
    return instance_list


async def terminate(credentials, *, instance_ids, verbose=False):
    assert isinstance(instance_ids, list) or isinstance(instance_ids,
                                                        tuple), instance_ids
    browser, page = await start_session(credentials)

    codegen = jinja2.Template('''() => {
        var xhr = new XMLHttpRequest();
        xhr.open("POST",
                 "https://lambdalabs.com/api/cloud/instances-rpc",
                 false);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.send(JSON.stringify({
            method: "terminate",
            params: {instance_ids: {{instance_ids}}}
        }));
        return JSON.parse(xhr.responseText);
    }''')
    response = await page.evaluate(
        codegen.render(instance_ids=list(instance_ids)))
    req_error = response['error']
    if req_error is None:
        if verbose:
            print(f'Terminated instances {list(instance_ids)}')
        await browser.close()
        return True
    else:
        if verbose:
            print(f'Error: {req_error}')
        else:
            await browser.close()
            raise LambdaError(req_error)
        await browser.close()
        return False


async def show_usage(credentials, show_all=False, verbose=False):
    browser, page = await start_session(credentials)

    # get account metadata
    await page.goto('https://lambdalabs.com/cloud/usage')
    account_data = await page.evaluate('''() => {
        return document.querySelector("section.view").getAttribute('ng-init');
    }''')
    account_data = (account_data.encode('latin1').decode(
        'unicode-escape').encode('latin1').decode('utf-8'))
    account_data = json.loads(account_data[6:-2])
    account_id = account_data['id']

    # get usage information
    await page.goto(
        f'https://lambdalabs.com/api/cloud/usage?account_id={account_id}')
    usage_list = await page.evaluate('''() => {
        return JSON.parse(document.body.innerText);
    }''')

    # display billing info
    if len(usage_list) == 0:
        if verbose:
            print('No usage information available.')
        return []

    active_months = []
    for month_usage in usage_list:
        period = month_usage['period']
        total = month_usage['total']
        total_pretty = month_usage['total_pretty']
        if total == 0:
            continue

        instance_bills = month_usage['instance_bills']
        table = prettytable.PrettyTable(
            align='l',
            border=False,
            field_names=['ID', 'INSTANCE_TYPE', 'RATE', 'USAGE', 'SPEND'])
        table.left_padding_width = 0
        table.right_padding_width = 2

        for bill in instance_bills:
            instance = bill['instance']
            rate = bill['hourly_cost_pretty']
            hours_used = bill['hours_used_pretty']
            table.add_row([
                instance['id'], instance['ttype'], f'{rate}/hour',
                f'{hours_used} hours', bill['spend_pretty']
            ])

        if len(active_months) > 0 and show_all and verbose:
            print()
        if verbose:
            print(f'{Style.BRIGHT}{period.upper()}{Style.RESET_ALL} '
                  f'({Fore.CYAN}{total_pretty}{Style.RESET_ALL})')
        if show_all and verbose:
            print(table)
        active_months.append(month_usage)

    await browser.close()
    return active_months


def ignore_handler(loop, context):
    del loop, context  # ignore everything


class LambdaError(Exception):
    __module__ = 'builtins'


class Metadata:
    """Local metadata for a Lambda Labs instance."""

    def __init__(self):
        self._metadata_path = os.path.expanduser(LOCAL_METADATA_PATH)
        self._metadata = {}
        if os.path.exists(self._metadata_path):
            with open(self._metadata_path, 'r') as f:
                self._metadata = json.load(f)

    def __getitem__(self, instance_id):
        return self._metadata.get(instance_id)

    def __setitem__(self, instance_id, value):
        self._metadata[instance_id] = value
        with open(self._metadata_path, 'w') as f:
            json.dump(self._metadata, f)


class Lambda:

    def __init__(self, cli=False):
        self._credentials_path = os.path.expanduser(CREDENTIALS_PATH)
        self._credentials = None
        self._cli = cli
        if os.path.exists(self._credentials_path):
            with open(self._credentials_path, 'r') as f:
                lines = [line.strip() for line in f.readlines() if '=' in line]
                self._credentials = {
                    line.split(' = ')[0]: line.split(' = ')[1]
                    for line in lines
                }

    def auth(self):
        """Authenticate with Lambda Labs API."""
        email_prompt = 'Lambda Email: '
        pw_prompt = 'Lambda Password: '
        if self._credentials is not None:
            email = '*' * 16 + self._credentials['email'][-4:]
            pw = '*' * 16 + self._credentials['password'][-4:]
            email_prompt = f'Lambda Email [{email}]: '
            pw_prompt = f'Lambda Password [{pw}]: '
        self._credentials = {
            'email': input(email_prompt),
            'password': getpass.getpass(pw_prompt)
        }

        # save credentials
        pathlib.Path(self._credentials_path).parent.mkdir(parents=True,
                                                          exist_ok=True)
        with open(self._credentials_path, 'w') as f:
            for key, value in self._credentials.items():
                f.write(f'{key} = {value}\n')

    def _run_api_fn(self, context):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.set_exception_handler(ignore_handler)
        result = loop.run_until_complete(context)
        if not self._cli:
            return result

    def up(self,
           instance_type='gpu.1x.rtx6000',
           key=None,
           region='us-tx-1',
           count=1):
        """Start a new instance."""
        ctx = provision(self._credentials,
                        instance_type=instance_type,
                        ssh_key_id=key,
                        region=region,
                        count=count,
                        verbose=self._cli)
        return self._run_api_fn(ctx)

    def rm(self, *instance_ids):
        """Terminate instances."""
        ctx = terminate(self._credentials,
                        instance_ids=instance_ids,
                        verbose=self._cli)
        return self._run_api_fn(ctx)

    def ls(self):
        """List existing instances."""
        ctx = list_instances(self._credentials, verbose=self._cli)
        return self._run_api_fn(ctx)

    def keys(self):
        """List registered SSH keys."""
        ctx = list_ssh_keys(self._credentials, verbose=self._cli)
        return self._run_api_fn(ctx)

    def key_add(self, key, name=None):
        """Add a new SSH key."""
        if os.path.exists(os.path.expanduser(key)):
            with open(os.path.expanduser(key), 'r') as f:
                key = f.read().strip()

        ctx = add_ssh_key(self._credentials,
                          key=key,
                          name=name,
                          verbose=self._cli)
        return self._run_api_fn(ctx)

    def usage(self, all=False):
        """Show instance usage and billing. Use --all to show details."""
        ctx = show_usage(self._credentials, show_all=all, verbose=self._cli)
        return self._run_api_fn(ctx)

    def catalog(self):
        """Show available instance types."""
        df = pandas.read_csv(here / 'catalog.csv')
        table = prettytable.PrettyTable(align='l',
                                        border=False,
                                        field_names=[
                                            'INSTANCE_TYPE', 'GPUs',
                                            'VRAM_PER_GPU', 'vCPUs', 'RAM',
                                            'STORAGE', 'HOURLY_PRICE'
                                        ])
        table.left_padding_width = 0
        table.right_padding_width = 2

        for _, row in df.iterrows():
            instance_type = row['InstanceType']
            acc_name = row['AcceleratorName']
            acc_count = row['AcceleratorCount']
            host_mem = row['MemoryGiB']
            gpu_mem = row['GpuMemGB']
            hourly_price = row['Price']
            vcpus = row['vCPUs']
            storage = row['Storage']
            table.add_row([
                instance_type, f'{acc_count}x NVIDIA {acc_name}',
                f'{gpu_mem}GB', vcpus, f'{host_mem}GiB', storage,
                f'$ {hourly_price:.2f}'
            ])
        if self._cli:
            print(table)
        else:
            return df
