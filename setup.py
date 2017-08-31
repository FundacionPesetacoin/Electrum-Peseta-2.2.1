#!/usr/bin/python

# python setup.py sdist --format=zip,gztar

from setuptools import setup
import os
import sys
import platform
import imp


version = imp.load_source('version', 'lib/version.py')
i18n = imp.load_source('i18n', 'lib/i18n.py')
util = imp.load_source('util', 'lib/util.py')

if sys.version_info[:3] < (2, 7, 0):
    sys.exit("Error: Electrum requires Python version >= 2.7.0...")



if (len(sys.argv) > 1) and (sys.argv[1] == "install"):
    # or (platform.system() != 'Windows' and platform.system() != 'Darwin'):
    print "Including all files"
    data_files = []
    usr_share = util.usr_share_dir()
    if not os.access(usr_share, os.W_OK):
        try:
            os.mkdir(usr_share)
        except:
            sys.exit("Error: cannot write to %s.\nIf you do not have root permissions, you may install Electrum in a virtualenv.\nAlso, please note that you can run Electrum without installing it on your system."%usr_share)

    data_files += [
        (os.path.join(usr_share, 'applications'), ['electrum-peseta.desktop']),
        (os.path.join(usr_share, 'app-install', 'icons'), ['icons/electrum-peseta.png'])
    ]
    if not os.path.exists('locale'):
        os.mkdir('locale')
    for lang in os.listdir('locale'):
        if os.path.exists('locale/%s/LC_MESSAGES/electrum.mo' % lang):
            data_files.append((os.path.join(usr_share, 'locale/%s/LC_MESSAGES' % lang), ['locale/%s/LC_MESSAGES/electrum.mo' % lang]))


    appdata_dir = os.path.join(usr_share, "electrum-peseta")
    data_files += [
        (appdata_dir, ["data/README"]),
        (os.path.join(appdata_dir, "cleanlook"), [
            "data/cleanlook/name.cfg",
            "data/cleanlook/style.css"
        ]),
        (os.path.join(appdata_dir, "sahara"), [
            "data/sahara/name.cfg",
            "data/sahara/style.css"
        ]),
        (os.path.join(appdata_dir, "dark"), [
            "data/dark/name.cfg",
            "data/dark/style.css"
        ]),
        (os.path.join(appdata_dir, "peseta"), [
            "data/peseta/name.cfg",
            "data/peseta/style.css"
        ])
    ]

    for lang in os.listdir('data/wordlist'):
        data_files.append((os.path.join(appdata_dir, 'wordlist'), ['data/wordlist/%s' % lang]))
else:
    data_files = []

setup(
    name="Electrum-Peseta",
    version=version.ELECTRUM_VERSION,
    install_requires=[
        'slowaes',
        'ecdsa>=0.9',
        'pbkdf2',
        'requests',
        'pyasn1',
        'pyasn1-modules',
        'qrcode',
        'SocksiPy-branch',
        'tlslite',
        'btcutils',
        'ltc_scrypt'
    ],
    package_dir={
        'electrum_peseta': 'lib',
        'electrum_peseta_gui': 'gui',
        'electrum_peseta_plugins': 'plugins',
    },
    scripts=['electrum-peseta'],
    data_files=data_files,
    py_modules=[
        'electrum_peseta.account',
        'electrum_peseta.auxpow',
        'electrum_peseta.pesetacoin',
        'electrum_peseta.blockchain',
        'electrum_peseta.bmp',
        'electrum_peseta.commands',
        'electrum_peseta.daemon',
        'electrum_peseta.i18n',
        'electrum_peseta.interface',
        'electrum_peseta.mnemonic',
        'electrum_peseta.msqr',
        'electrum_peseta.network',
        'electrum_peseta.network_proxy',
        'electrum_peseta.old_mnemonic',
        'electrum_peseta.paymentrequest',
        'electrum_peseta.paymentrequest_pb2',
        'electrum_peseta.plugins',
        'electrum_peseta.qrscanner',
        'electrum_peseta.scrypt',
        'electrum_peseta.simple_config',
        'electrum_peseta.synchronizer',
        'electrum_peseta.transaction',
        'electrum_peseta.util',
        'electrum_peseta.verifier',
        'electrum_peseta.version',
        'electrum_peseta.wallet',
        'electrum_peseta.x509',
        'electrum_peseta_gui.gtk',
        'electrum_peseta_gui.qt.__init__',
        'electrum_peseta_gui.qt.amountedit',
        'electrum_peseta_gui.qt.console',
        'electrum_peseta_gui.qt.history_widget',
        'electrum_peseta_gui.qt.icons_rc',
        'electrum_peseta_gui.qt.installwizard',
        'electrum_peseta_gui.qt.lite_window',
        'electrum_peseta_gui.qt.main_window',
        'electrum_peseta_gui.qt.network_dialog',
        'electrum_peseta_gui.qt.password_dialog',
        'electrum_peseta_gui.qt.paytoedit',
        'electrum_peseta_gui.qt.qrcodewidget',
        'electrum_peseta_gui.qt.qrtextedit',
        'electrum_peseta_gui.qt.receiving_widget',
        'electrum_peseta_gui.qt.seed_dialog',
        'electrum_peseta_gui.qt.transaction_dialog',
        'electrum_peseta_gui.qt.util',
        'electrum_peseta_gui.qt.version_getter',
        'electrum_peseta_gui.stdio',
        'electrum_peseta_gui.text',
        'electrum_peseta_plugins.btchipwallet',
        'electrum_peseta_plugins.coinbase_buyback',
        'electrum_peseta_plugins.cosigner_pool',
        'electrum_peseta_plugins.exchange_rate',
        'electrum_peseta_plugins.greenaddress_instant',
        'electrum_peseta_plugins.labels',
        'electrum_peseta_plugins.trezor',
        'electrum_peseta_plugins.virtualkeyboard',
		'electrum_peseta_plugins.plot',
    ],
    description="Lightweight Pesetacoin Wallet",
    author="Thomas Voegtlin",
    author_email="thomasv1@gmx.de",
    license="GNU GPLv3",
    url="https://electrum.pesetacoin.info",
    long_description="""Lightweight Pesetacoin Wallet"""
)
