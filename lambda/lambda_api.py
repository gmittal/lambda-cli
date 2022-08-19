import asyncio
import getpass
import json
import os
import pathlib

import jinja2
import prettytable

from pyppeteer import launch

LOGIN_URL = 'https://lambdalabs.com/cloud/login'
DASHBOARD_URL = 'https://lambdalabs.com/cloud/dashboard/instances'
CREDENTIALS_PATH = '~/.lambda/credentials'
SESSION_COOKIE_PATH = '~/.lambda/session'


async def start_session(credentials):
    browser = await launch(headless=True)
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
        await page.screenshot({'path': os.path.expanduser('~/.lambda/debug_login.png')})
        await page.goto(DASHBOARD_URL)

    # show dashboard login
    await page.screenshot({'path': os.path.expanduser('~/.lambda/debug_list.png')})

    # grab session cookie
    client = await page.target.createCDPSession()
    cookies = (await client.send('Network.getAllCookies'))['cookies']
    for cookie in cookies:
        if cookie['name'] == 'sessionid':
            with open(session_cookie_path, 'w') as f:
                f.write(json.dumps(cookie))
            break


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

    table = prettytable.PrettyTable(align='l', border=False, field_names=['ID', 'IP', 'INSTANCE_TYPE', 'STATE'])
    table.left_padding_width = 0
    table.right_padding_width = 2
    for instance in instance_list['data']:
        instance_state = instance['state'].upper()
        if instance_state == 'CONTACTABLE':
            instance_state = 'RUNNING'
        table.add_row([instance['id'], instance['ipv4'], instance['ttype'], instance_state])
    print(table)


async def list_instances(credentials):
    browser, page = await start_session(credentials)
    instance_list = await get_instances(page)
    display_instance_list(instance_list)
    await browser.close()


async def provision(credentials, *, instance_type):
    browser, page = await start_session(credentials)

    codegen = jinja2.Template('''() => {
        var xhr = new XMLHttpRequest();
        xhr.open("POST", "https://lambdalabs.com/api/cloud/instances-rpc", false);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.send(JSON.stringify({
            method: "launch",
            params: {ttype: "{{instance_type}}",
                    quantity: 1,
                    region: "us-tx-1",
                    public_key_id: "be49bd118ea048a0b3fa50602e1f4d76",
                    filesystem_id: null}
        }));
        return JSON.parse(xhr.responseText);
    }''')
    response = await page.evaluate(codegen.render(instance_type=instance_type))
    req_error = response['error']

    if req_error is None:
        if len(response['data']) == 1:
            api_error = response['data'][0].get('err', None)
            if api_error is not None:
                print(f'Error: {api_error}')
                await browser.close()
                return
        instance_page = await browser.newPage()
        instance_list = await get_instances(instance_page)
        display_instance_list(instance_list)
    else:
        print(f'Error: {req_error}')

    await browser.close()


async def terminate(credentials, *, instance_ids):
    assert isinstance(instance_ids, list) or isinstance(instance_ids, tuple), instance_ids
    browser, page = await start_session(credentials)

    codegen = jinja2.Template('''() => {
        var xhr = new XMLHttpRequest();
        xhr.open("POST", "https://lambdalabs.com/api/cloud/instances-rpc", false);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.send(JSON.stringify({
            method: "terminate",
            params: {instance_ids: {{instance_ids}}}
        }));
        return JSON.parse(xhr.responseText);
    }''')
    response = await page.evaluate(codegen.render(instance_ids=list(instance_ids)))
    req_error = response['error']
    if req_error is None:
        print(f'Terminated instances {list(instance_ids)}')
    else:
        print(f'Error: {req_error}')

    await browser.close()


def ignore_handler(loop, context):
    del loop, context  # ignore everything


class Lambda:
    def __init__(self):
        self._credentials_path = os.path.expanduser(CREDENTIALS_PATH)
        self._credentials = None
        if os.path.exists(self._credentials_path):
            with open(self._credentials_path, 'r') as f:
                lines = [line.strip() for line in f.readlines() if '=' in line]
                self._credentials = {line.split(' = ')[0]: line.split(' = ')[1] for line in lines}

    def auth(self):
        """Authenticate with Lambda Labs API."""
        email_prompt = 'Lambda Email: '
        pw_prompt = 'Lambda Password: '
        if self._credentials is not None:
            email = '*' * 16 + self._credentials['email'][-4:]
            pw = '*' * 16 + self._credentials['password'][-4:]
            email_prompt = f'Lambda Email [{email}]: '
            pw_prompt = f'Lambda Password [{pw}]: '
        self._credentials = {'email': input(email_prompt),
                            'password': getpass.getpass(pw_prompt)}

        # save credentials
        pathlib.Path(self._credentials_path).parent.mkdir(parents=True, exist_ok=True)
        with open(self._credentials_path, 'w') as f:
            for key, value in self._credentials.items():
                f.write(f'{key} = {value}\n')

    def up(self, instance_type='gpu.1x.rtx6000'):
        """Start a new instance."""
        loop = asyncio.get_event_loop()
        loop.set_exception_handler(ignore_handler)
        loop.run_until_complete(provision(self._credentials, instance_type=instance_type))

    def rm(self, *instance_ids):
        """Terminate instances."""
        loop = asyncio.get_event_loop()
        loop.set_exception_handler(ignore_handler)
        loop.run_until_complete(terminate(self._credentials, instance_ids=instance_ids))

    def ls(self):
        """List existing instances."""
        loop = asyncio.get_event_loop()
        loop.set_exception_handler(ignore_handler)
        loop.run_until_complete(list_instances(self._credentials))
