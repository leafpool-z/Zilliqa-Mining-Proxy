# -*- coding: utf-8 -*-
# Zilliqa Mining Proxy
# Copyright (C) 2019  Gully Chen
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
Run mock Zilliqa nodes to send PoW works to proxy
python zil_simulator.py run --nodes=1
"""

import os
import sys
import time
import random
import asyncio
import argparse
from aiohttp import ClientSession
from jsonrpcclient.clients.aiohttp_client import AiohttpClient

from zilpool.common.utils import load_config
from zilpool.pyzil.crypto import ZilKey
from zilpool.pyzil import crypto, ethash


cur_dir = os.path.dirname(os.path.abspath(__file__))
config_file = os.path.join(cur_dir, "nodes.conf")
default_config = load_config(config_file)
cur_block_file = os.path.join(cur_dir, "cur_block.tmp")


class Node:
    def __init__(self, node_id, key, args):
        self.key = key
        self.args = args
        self.node_id = node_id
        self.block = 0
        self.pow_end_time = None

        self.rpc_client = None

    @property
    def pow_timeout(self):
        return int(self.pow_end_time - time.time())

    def __str__(self):
        return f"[Node {self.node_id}]"

    def log(self, msg):
        print(f"{self}  {msg}")

    async def do_request(self, method, req):
        self.log(f"request {method}")
        resp = await self.rpc_client.request(method, req, trim_log_values=True)
        self.log(f"response {resp.data}")
        return resp.data

    def create_work(self):
        header = crypto.rand_bytes(32)
        block_num = crypto.int_to_bytes(self.block, n_bytes=8)

        return {
            "header": header,              # 32 bytes
            "block_num": block_num,        # 8 bytes
        }

    def make_work_request(self, work, diff):
        timeout = crypto.int_to_bytes(self.pow_timeout, n_bytes=4)
        boundary = ethash.difficulty_to_boundary(diff)

        # requests are bytes
        bytes_reqs = [
            self.key.keypair_bytes.public,    # 33 bytes
            work["header"],                   # 32 bytes
            work["block_num"],                # 8 bytes
            boundary,                         # 32 bytes
            timeout,                          # 4 bytes
        ]

        # convert to bytes to sign
        bytes_to_sign = b"".join(bytes_reqs)
        assert len(bytes_to_sign) == 33 + 32 * 2 + 8 + 4

        signature = self.key.sign(bytes_to_sign)    # signature is hex string, len 128
        assert len(signature) == 128
        signature = "0x" + signature

        # convert to hex string starts with "0x"
        req = [crypto.bytes_to_hex_str_0x(b) for b in bytes_reqs]
        # append signature
        req.append(signature)
        return req

    def make_check_request(self, work, diff):
        boundary = ethash.difficulty_to_boundary(diff)

        # requests are bytes
        bytes_reqs = [
            self.key.keypair_bytes.public,  # 33 bytes
            work["header"],                 # 32 bytes
            boundary,                       # 32 bytes
        ]

        # convert to bytes to sign
        bytes_to_sign = b"".join(bytes_reqs)
        assert len(bytes_to_sign) == 33 + 32 * 2

        signature = self.key.sign(bytes_to_sign)  # signature is hex string, len 128
        assert len(signature) == 128
        signature = "0x" + signature

        # convert to hex string starts with "0x"
        req = [crypto.bytes_to_hex_str_0x(b) for b in bytes_reqs]
        # append signature
        req.append(signature)
        return req

    def make_verify_request(self, work, diff, verify=True):
        boundary = ethash.difficulty_to_boundary(diff)

        byte_verify = b"\x01" if verify else b"\x00"

        # requests are bytes
        bytes_reqs = [
            self.key.keypair_bytes.public,  # 33 bytes
            byte_verify,                    # 1  bytes
            work["header"],                 # 32 bytes
            boundary,                       # 32 bytes
        ]

        # convert to bytes to sign
        bytes_to_sign = b"".join(bytes_reqs)
        assert len(bytes_to_sign) == 33 + 1 + 32 * 2

        signature = self.key.sign(bytes_to_sign)  # signature is hex string, len 128
        assert len(signature) == 128
        signature = "0x" + signature

        # convert to hex string starts with "0x"
        req = [crypto.bytes_to_hex_str_0x(b) for b in bytes_reqs]
        # append signature
        req.append(signature)
        return req

    async def start_pow(self, work, diff):
        self.log(f"starting pow with difficulty {diff}")

        # 1. send PoW request to Proxy
        res = await self.request_work(work, diff)
        if not res:
            self.log(" zil_requestWork failed")
            return

        # 2. waiting for Proxy doing PoW
        self.log("sleep 10 seconds")
        await asyncio.sleep(10)

        # 3. check result if finished
        res = await self.get_result(work, diff)
        if not res:
            self.log(" zil_checkWorkStatus failed")
            return

        # 4. tell the Proxy result is valid or not
        res = await self.verify_result(work, diff)
        if not res:
            self.log(" zil_verifyResult failed")
            return

        # 5. return True here
        return True

    async def build_request_and_run(self, method, work, diff,
                                    func_build_req, func_resp,
                                    retry=5, sleep=5.0):
        req = func_build_req(work, diff)
        for i in range(retry):
            resp = await self.do_request(method, req)
            res = func_resp(resp)
            if not res:
                await asyncio.sleep(sleep)
                continue
            return res

        self.log(f"{method}:  retry exhausted, stop pow this round")
        return False

    async def request_work(self, work, diff, retry=3):
        return await self.build_request_and_run(
            "zil_requestWork", work, diff,
            self.make_work_request, lambda resp: resp.result,
            retry=retry, sleep=2
        )

    async def get_result(self, work, diff, retry=5):
        return await self.build_request_and_run(
            "zil_checkWorkStatus", work, diff,
            self.make_check_request, lambda resp: resp.result[0],
            retry=retry, sleep=self.pow_timeout / retry
        )

    async def verify_result(self, work, diff, retry=3):
        return await self.build_request_and_run(
            "zil_verifyResult", work, diff,
            self.make_verify_request, lambda resp: resp.result,
            retry=retry, sleep=2
        )

    async def do_pow(self, session, block):
        self.rpc_client = AiohttpClient(session, self.args.proxy, basic_logging=True)

        self.block = block
        self.pow_end_time = time.time() + self.args.pow

        waiting = random.randrange(1, 5)
        self.log("=" * 40)
        self.log(f"starting in {waiting} seconds ......")
        await asyncio.sleep(waiting)

        work = self.create_work()

        self.log(f"Start Shard PoW at block {self.block}")
        await self.start_pow(work, self.args.diff)

        self.log(f"Start DS PoW at block {self.block}")
        await self.start_pow(work, self.args.ds_diff)

        self.log(f"Pow Done at block {self.block}")


def load_keys(args):
    keys = []

    if not os.path.isfile(args.keys):
        print(f"keys file not found, pls run 'zil_simulator.py keygen' first")
        exit(1)

    with open(args.keys, "r") as f:
        for line in f.readlines():
            public, private = line.strip().split(" ")
            key = ZilKey(str_public=public, str_private=private)
            keys.append(key)
    return keys


async def start_loop(loop, args, nodes):
    cur_block = args.block

    async with ClientSession(loop=loop) as session:
        while True:
            print(f"[LOOP] Start PoW at block {cur_block}")

            tasks = [node.do_pow(session, cur_block) for node in nodes]
            await asyncio.wait(tasks, timeout=args.pow)

            print(f"[LOOP] Sleep {args.epoch} seconds, waiting for next POW")
            await asyncio.sleep(args.epoch)

            cur_block += 1

            with open(cur_block_file, "w") as f:
                f.write(f"{cur_block}")


def run(args):
    print(f"Proxy Server: {args.proxy}")
    print(f"Starting to run {args.nodes} mock ZIL nodes")
    print(f"Loading keypairs ... from {args.keys}")

    keys = load_keys(args)
    print(f"{len(keys)} keypairs loaded")

    if len(keys) < args.nodes:
        print(f"not enough keypairs for {args.nodes} nodes, pls run keygen first")

    rand_keys = random.sample(keys, args.nodes)
    nodes = [Node(i, key, args) for i, key in enumerate(rand_keys)]
    print(f"{len(nodes)} nodes created, starting to run ...")

    # set up aio client session and run
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_loop(loop, args, nodes))


def keygen(args):
    print(f"Starting to generate keypairs for ZIL nodes")
    keys = []
    for i in range(args.nodes):
        key = ZilKey.generate_key_pair()
        keys.append(" ".join(key.keypair_str))

    with open(args.keys, "w") as f:
        f.write("\n".join(keys))

    print(f"{len(keys)} keypairs generated into > {args.keys}")


def main():
    args = build_args()
    if args.block == -1:
        # try to load from cur_block.tmp
        try:
            with open(cur_block_file) as f:
                block = int(f.read()) + 10
        except:
            block = default_config["start_block"]

        args.block = block

    commands[args.command](args)


commands = {
    "run": run,
    "keygen": keygen
}


def build_args():
    parser = argparse.ArgumentParser(
        description="Run mock ZIL node, send PoW work to proxy",
        usage='''
zil_simulator <command> [<args>]
    The commands are:
        run         Run mocked ZIL nodes, send PoW works to Proxy
        keygen      Generate keys for nodes
 ''')

    parser.add_argument("command", nargs="?", default="run",
                        help=f"command in {list(commands.keys())}")
    args = parser.parse_args(sys.argv[1:2])
    if args.command not in commands:
        print(f"unknown command '{args.command}'")
        parser.print_help()
        exit(1)

    parser.add_argument("-p", "--proxy", default=default_config["proxy_server"],
                        help=f"host of proxy server, default {default_config['proxy_server']}")
    parser.add_argument("-n", "--nodes", default=default_config["nodes"], type=int,
                        help=f"# of nodes to run, default {default_config['nodes']}")
    parser.add_argument("-pow", "--pow", default=default_config["pow_window"], type=int,
                        help=f"seconds of PoW window, default {default_config['pow_window']}")
    parser.add_argument("-e", "--epoch", default=default_config["epoch_time"], type=int,
                        help=f"seconds of a DS epoch, default {default_config['epoch_time']}")
    parser.add_argument("-b", "--block", default=-1, type=int,
                        help=f"block num to start, default load from cur_block.log")
    parser.add_argument("-d", "--diff", default=default_config["difficulty"], type=int,
                        help=f"shards difficulty, default {default_config['difficulty']}")
    parser.add_argument("-ds", "--ds_diff", default=default_config["ds_difficulty"], type=int,
                        help=f"DS difficulty, default {default_config['ds_difficulty']}")
    parser.add_argument("-k", "--keys", default=default_config["keys_file"],
                        help=f"file of keys, default {default_config['keys_file']}")

    return parser.parse_args()


if __name__ == "__main__":
    main()

