from eth_account import Account
from tronpy.keys import PrivateKey
import secrets

Account.enable_unaudited_hdwallet_features()
acct = Account.create(secrets.token_hex(32))
print("=== EVM WALLET - FOR BSC / ETH / POLYGON etc ===")
print("Address:", acct.address)
print("Private Key:", acct.key.hex())
print("")

priv_key = PrivateKey.random()
print("=== TRON WALLET - FOR TRC20 ===")
print("Address:", priv_key.public_key.to_base58check_address())
print("Private Key:", priv_key.hex())
print("")
input("Press ENTER to close")