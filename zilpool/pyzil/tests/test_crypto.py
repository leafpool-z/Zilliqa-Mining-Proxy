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

import re
import pytest

from zilpool.pyzil import crypto


def path_join(*path):
    import os
    cur_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(cur_dir, *path)


def load_ts_fixtures(file_name):
    with open(file_name) as f:
        content = f.read()

    results = []
    re_list = re.compile(r"\{(?P<entry>.+?)\},", re.DOTALL)
    for match in re_list.finditer(content):
        entry = match.group("entry")
        items = [item.strip() for item in entry.strip().split(",") if item and item.strip()]
        entry_dict = {}
        for item in items:
            key, value = [v.strip() for v in item.strip().split(":", 2) if v and v.strip()]
            entry_dict[key] = value.strip("'").strip('"')

        results.append(entry_dict)

    return results


class TestCrypto:
    def test_rand(self):
        assert isinstance(crypto.rand_bytes(12), bytes)
        assert isinstance(crypto.rand_hex_str(12), str)

        assert crypto.rand_bytes(1) != crypto.rand_bytes(1)
        assert len(crypto.rand_bytes(11)) == 11
        assert len(crypto.rand_bytes(999)) == 999

        for i in range(-99, 1):
            with pytest.raises(ValueError):
                crypto.rand_bytes(i)

        assert crypto.rand_hex_str(2) != crypto.rand_hex_str(2)
        assert len(crypto.rand_hex_str(11)) == 11
        assert len(crypto.rand_hex_str(999)) == 999
        assert len(crypto.rand_hex_str(1000)) == 1000
        assert len(crypto.rand_hex_str(999, prefix="0x")) == 999 + 2

        for i in range(-99, 1):
            with pytest.raises(ValueError):
                crypto.rand_hex_str(i)

    def test_hex_str(self):
        hex_str = "DEADBEEF"
        hex_str_odd = "deadbee"
        bin_bytes = b"\xde\xad\xbe\xef"
        bin_bytes_odd = b"\x0d\xea\xdb\xee"

        assert crypto.hex_str_to_bytes(hex_str) == bin_bytes
        assert crypto.bytes_to_hex_str(bin_bytes) == hex_str.lower()

        assert crypto.hex_str_to_int(hex_str) == 0xDEADBEEF
        assert crypto.bytes_to_int(bin_bytes) == 0xdeadbeef

        assert crypto.hex_str_to_int(hex_str_odd) == 0xDEADBEE
        assert crypto.bytes_to_int(bin_bytes_odd) == 0xDEADBEE

    def test_hex_str_padding(self):
        dead_beef = 0xDEADBEEF

        assert len(crypto.int_to_bytes(dead_beef)) == crypto.TOKEN_NUM_BYTES
        assert crypto.int_to_bytes(dead_beef, n_bytes=None) == b"\xde\xad\xbe\xef"

        for i in range(4):
            with pytest.raises(OverflowError, message="Expecting OverflowError:"):
                crypto.int_to_bytes(dead_beef, n_bytes=i)

        for i in range(5, 130):
            assert len(crypto.int_to_bytes(dead_beef, n_bytes=i)) == i

    def test_zil_mykey(self):
        key = crypto.ZilKey.load_mykey_txt(path_join("mykey.txt"))
        assert key.address == "967e40168af66f441b73c0146e26069bfc3accc7"

        with pytest.raises(AssertionError):
            crypto.ZilKey("02A349FA10F0E6A614A38D6033588A422357F2C60AF2EEBAE15D06498DF8AF0B05",
                          "75889EA1AF5D402B69E61C654C74D8B569E363D2E271E1E6E2B63FDB9B635173")

        new_key = crypto.ZilKey(
            "02A349FA10F0E6A614A38D6033588A422357F2C60AF2EEBAE15D06498DF8AF0B05",
            "75889EA1AF5D402B69E61C654C74D8B569E363D2E271E1E6E2B63FDB9B635174"
        )

        assert key == new_key
        assert key != crypto.ZilKey.generate_key_pair()

        pub_key = "0x03949D29723DA4B2628224D3EC8E74C518ACA98C6630B00527F86B8349E982CB57"
        private_key = "05C3CF3387F31202CD0798B7AA882327A1BD365331F90954A58C18F61BD08FFC"
        wallet_address = "95B27EC211F86748DD985E1424B4058E94AA5814"

        new_key = crypto.ZilKey(str_public=pub_key)
        assert new_key.address == wallet_address.lower()

        new_key = crypto.ZilKey(str_private=private_key)
        assert crypto.hex_str_to_int(new_key.keypair_str.public) == crypto.hex_str_to_int(pub_key)

        assert new_key.address == wallet_address.lower()

    def test_sign_verify(self):
        for i in range(10):
            key = crypto.ZilKey.generate_key_pair()
            l = 1 + i * 512
            msg = crypto.rand_bytes(l) + crypto.rand_string(l).encode()
            signature = key.sign(msg)
            assert key.verify(signature, msg)

    def test_load_mykey(self):
        key = crypto.ZilKey.load_mykey_txt(path_join("mykey.txt"))
        assert key.address == "967e40168af66f441b73c0146e26069bfc3accc7"

        key2 = crypto.ZilKey.load_mykey_txt(path_join("mykey2.txt"))
        assert key2.address == "e2406d084955e2d2ba8e8eaf7fe1c6a3e9ab3ea9"

    def test_address(self):
        addresses = load_ts_fixtures(path_join("address.fixtures.ts"))
        for addr in addresses:
            from_file = addr["address"].lower()
            from_private = crypto.address_from_private_key(addr["private"])
            assert from_private == from_file
            from_public = crypto.address_from_public_key(addr["public"])
            assert from_public == from_file

    def test_keypairs(self):
        keypairs = load_ts_fixtures(path_join("keypairs.fixtures.ts"))
        for pair in keypairs:
            key_from_private = crypto.ZilKey(str_private=pair["private"])
            key_from_public = crypto.ZilKey(str_public=pair["public"])

            assert key_from_private.pub_key == key_from_public.pub_key

