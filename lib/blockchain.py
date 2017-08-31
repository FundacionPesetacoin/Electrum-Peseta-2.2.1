#!/usr/bin/env python
#
# Electrum - lightweight Bitcoin client
# Copyright (C) 2012 thomasv@ecdsa.org
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import threading, time, Queue, os, sys, shutil, traceback, json, auxpow
import zlib
from decimal import Decimal
from util import user_dir, appdata_dir, print_error, cdiv, print_msg
from pesetacoin import *
from transaction import BCDataStream

try:
    from ltc_scrypt import getPoWHash as PoWHash
except ImportError:
    print_msg("Warning: ltc_scrypt not available, using fallback")
    from scrypt import scrypt_1024_1_1_80 as PoWHash

import pprint
pp = pprint.PrettyPrinter(indent=4)

#max_target = 0x00000000FFFF0000000000000000000000000000000000000000000000000000
max_target = 0x00000FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF

# https://github.com/FundacionPesetacoin/Pesetacoin-0.9.1-Oficial/blob/master/src/core.h#L39
auxpow_start = 32086

# Kimoto Gravity Well
# https://github.com/FundacionPesetacoin/Pesetacoin-0.9.1-Oficial/blob/master/src/main.cpp#L1493
kgw_start = 46000

# https://github.com/FundacionPesetacoin/Pesetacoin-0.9.1-Oficial/blob/master/src/main.cpp#L1431
# Kimoto Gravity Well FIX
kgw_fix   = 127500

# Dark Gravity Well
# https://github.com/FundacionPesetacoin/Pesetacoin-0.9.1-Oficial/blob/master/src/main.cpp#L1495
dgw_start = 582500

def bits_to_target(bits):
    """Convert a compact representation to a hex target."""
    MM = 256*256*256
    a = bits%MM
    if a < 0x8000:
        a *= 256
    target = (a) * pow(2, 8 * (bits/MM - 3))
    return target

def target_to_bits(target):
    """Convert a target to compact representation."""
    MM = 256*256*256
    c = ("%064X"%target)[2:]
    i = 31
    while c[0:2]=="00":
        c = c[2:]
        i -= 1

    c = int('0x'+c[0:6],16)
    if c >= 0x800000:
        c /= 256
        i += 1

    new_bits = c + MM * i
    return new_bits

class Blockchain(threading.Thread):

    def __init__(self, config, network):
        threading.Thread.__init__(self)
        self.daemon = True
        self.config = config
        self.network = network
        self.lock = threading.Lock()
        self.local_height = 0
        self.running = False
        self.headers_url = 'http://electrum.pesetacoin.info/blockchain_headers'
        self.set_local_height()
        self.queue = Queue.Queue()


    def height(self):
        return self.local_height


    def stop(self):
        with self.lock: self.running = False


    def is_running(self):
        with self.lock: return self.running


    def run(self):
        self.init_headers_file()
        self.set_local_height()
        print_error( "blocks:", self.local_height )

        with self.lock:
            self.running = True

        while self.is_running():

            try:
                result = self.queue.get()
            except Queue.Empty:
                continue

            if not result: continue

            i, header = result
            if not header: continue

            height = header.get('block_height')

            if height <= self.local_height:
                continue

            if height > self.local_height + 50:
                if not self.get_and_verify_chunks(i, header, height):
                    continue

            if height > self.local_height:
                # get missing parts from interface (until it connects to my chain)
                chain = self.get_chain( i, header )

                # skip that server if the result is not consistent
                if not chain:
                    print_error('e')
                    continue

                # verify the chain
                if self.verify_chain( chain ):
                    print_error("height:", height, i.server)
                    for header in chain:
                        self.save_header(header)
                else:
                    print_error("error", i.server)
                    # todo: dismiss that server
                    continue


            self.network.new_blockchain_height(height, i)



    def verify_chain(self, chain):

        first_header = chain[0]
        prev_header = self.read_header(first_header.get('block_height') - 1)

        for header in chain:

            height = header.get('block_height')

            prev_hash = self.hash_header(prev_header)
            bits, target = self.get_target(height, chain)
            _hash = self.hash_header(header)
            pow_hash = self.pow_hash_header(header)

            try:
                if height >= auxpow_start and header['version'] == 4653314:             #Pesetacoin blockchain
                    assert auxpow.verify(_hash, auxpow.get_our_chain_id(), header['auxpow'])
                    pow_hash = self.pow_hash_header(header['auxpow']['parent_block'])
                assert prev_hash == header.get('prev_block_hash')
                assert bits == header.get('bits')
                assert int('0x'+pow_hash,16) < target
            except Exception:
                print traceback.format_exc()
                print 'error validating chain at height ', height
                print 'block ', height, '(',_hash,') failed validation'
                pprint.pprint(header)
                print hex(bits), '==', hex(header.get('bits'))
                print int('0x'+pow_hash,16), '<', target
                return False

            prev_header = header

        return True



    def verify_chunk(self, index, hexdata):
        print 'verify chunk'
        hex_to_int = lambda s: int('0x' + s[::-1].encode('hex'), 16)

        data = hexdata.decode('hex')
        disk_data = ''
        height = index * 2016
        num = hex_to_int(data[0:4])
        data = data[4:]

        auxpowdata = data[num*88:]
        auxpowbaseoffset = 0

        if index == 0:
            previous_hash = ("0"*64)
        else:
            prev_header = self.read_header(index*2016-1)
            if prev_header is None: raise
            previous_hash = self.hash_header(prev_header)

        bits, target = self.get_target(height)

        chain = []
        for i in range(num):
            height = index * 2016 + i

            raw_header = data[i*88:(i+1)*88]
            disk_data += raw_header[0:80] # strip auxpow data

            header = self.header_from_string(raw_header)
            _hash = self.pow_hash_header(header)
            _prev_hash = self.hash_header(header)
            header['block_height'] = height

            if (i == 0):
               auxpowbaseoffset = header['auxpow_offset']

            start = header['auxpow_offset'] - auxpowbaseoffset
            end = start + header['auxpow_length']

            if (end > start):
                header['auxpow'] = self.auxpow_from_string(auxpowdata[start:end].decode('hex'))
                #print header['auxpow']

            chain.append(header)

            # pesetacoin retargets: every 120 blocks
            if (height % 120 == 0 or height >= kgw_start):
                bits, target = self.get_target(height, chain)

            #if height >= auxpow_start and header['version'] == 6422786: #TODO getAuxPowVersion()  #Dogecoin blockchain
            if height >= auxpow_start and header['version'] == 4653314:                           #Pesetacoin blockchain
                #todo: check that auxpow.get_chain_id(header) == auxpow.get_our_chain_id?
                #print header['auxpow']
                try:
                    assert auxpow.verify(_prev_hash, auxpow.get_our_chain_id(), header['auxpow'])
                except Exception as e:
                    print traceback.format_exc()
                    print 'block ', height, '(',_hash,') failed validation'
                    print 'auxpow failed verification'
                    pp.pprint(header['auxpow'])
                    raise e
                #pp.pprint(parent_header)
                _hash = self.pow_hash_header(header['auxpow']['parent_block'])
                #print _hash
                # todo: verify auxpow data
                #_hash = '' # auxpow.getHash()

            try:
                assert previous_hash == header.get('prev_block_hash')
                if height >= 555000:
                    assert bits == header.get('bits')
                    assert int('0x'+_hash,16) < target
            except Exception as e:
                print 'block ', height, ' failed validation'
                print previous_hash, '==', header.get('prev_block_hash')
                print hex(bits), '==', hex(header.get('bits'))
                print int('0x'+_hash,16), '<', target
                raise e

            if height % 120 == 0:
                print 'block ', height, ' validated'

            previous_header = header
            previous_hash = _prev_hash

        self.save_chunk(index, disk_data)
        print_error("validated chunk %d"%(height / 2016))

    #def parent_block_to_header(self, parent_block):
        #h = {}
        #h['version'] = parent_block['version']
        #h['prev_block_hash'] = parent_block['previousblockhash']
        #h['merkle_root'] = parent_block['merkleroot']
        #h['timestamp'] = parent_block['time']
        #h['bits'] = int(parent_block['bits'], 16) #not sure
        #h['nonce'] = parent_block['nonce']
        #return h

    def header_to_string(self, res):
        #Dogecoin blockchain
        s = int_to_hex(res.get('version'),4) \
            + rev_hex(res.get('prev_block_hash')) \
            + rev_hex(res.get('merkle_root')) \
            + int_to_hex(int(res.get('timestamp')),4) \
            + int_to_hex(int(res.get('bits')),4) \
            + int_to_hex(int(res.get('nonce')),4)

        #Pesetacoin blockchain
        #s = int_to_hex(res.get('version'),4) \
        #    + rev_hex(res.get('previousblockhash')) \
        #    + rev_hex(res.get('merkleroot')) \
        #    + int_to_hex(int(res.get('time')),4) \
        #    + int_to_hex(int(res.get('bits')),4) \
        #    + int_to_hex(int(res.get('nonce')),4)

        return s

    def auxpow_from_string(self, s):
        res = {}
        res['coinbasetx'], s = tx_from_string(s)
        res['coinbaseMerkleBranch'], res['coinbaseIndex'], s = merkle_branch_from_string(s)
        res['chainMerkleBranch'], res['chainIndex'], s = merkle_branch_from_string(s)
        res['parent_block'] = header_from_string(s)
        return res


    def header_from_string(self, s):
        # hmmm why specify 0x at beginning if 16 is already specified??
        hex_to_int = lambda s: int('0x' + s[::-1].encode('hex'), 16)
        h = {}
        h['version'] = hex_to_int(s[0:4])
        h['prev_block_hash'] = hash_encode(s[4:36])
        h['merkle_root'] = hash_encode(s[36:68])
        h['timestamp'] = hex_to_int(s[68:72])
        h['bits'] = hex_to_int(s[72:76])
        h['nonce'] = hex_to_int(s[76:80])
        if (len(s) > 80):
            h['auxpow_offset'] = hex_to_int(s[80:84])
            h['auxpow_length'] = hex_to_int(s[84:88])
        return h

    def pow_hash_header(self, header):
        return rev_hex(PoWHash(self.header_to_string(header).decode('hex')).encode('hex'))

    def hash_header(self, header):
        return rev_hex(Hash(self.header_to_string(header).decode('hex')).encode('hex'))

    def path(self):
        return os.path.join( self.config.path, 'blockchain_headers')

    # the file hosted on the server has extra data to index auxpow data
    # we need to remove that data to have 80 byte block headers instead of 88
    def remove_auxpow_indexes(self, filename):
        size = os.path.getsize(filename)
        f = open(self.path(), 'wb+')
        fa = open(filename, 'rb')

        i = 0
        j = 0
        while (i < size):
            fa.seek(i)
            f.seek(j)
            chunk = fa.read(80)
            f.write(chunk)
            j += 80
            i += 88

        f.close()
        fa.close()
        os.remove(filename)

    def init_headers_file(self):
        filename = self.path()
        if os.path.exists(filename):
            return

        try:
            import urllib, socket
            socket.setdefaulttimeout(30)
            print_error('downloading ', self.headers_url )

        ## Re-edition : by Alberto Hernandez - Pesetacoin Foundation 2017
            # Original lines :
            # urllib.urlretrieve(self.headers_url, filename + '_auxpow')
            # self.remove_auxpow_indexes(filename + '_auxpow')

            # New lines :
            urllib.urlretrieve(self.headers_url, filename + '.tmp')
            os.rename(filename + '.tmp', filename)
        # End Re-edition />

            print_error("done.")
        except Exception:
            print_error( 'download failed. creating file', filename  )
            open(filename,'wb+').close()
        self.set_local_height()
        print_error("%d blocks" % self.local_height)
        
    def convbits(self, target):
        # convert it to bits
        MM = 256*256*256
        c = ("%064X"%target)[2:]
        i = 31
        while c[0:2]=="00":
            c = c[2:]
            i -= 1

        c = int('0x'+c[0:6],16)
        if c >= 0x800000:
            c /= 256
            i += 1

        return c + MM * i

    def save_chunk(self, index, chunk):
        filename = self.path()
        f = open(filename,'rb+')
        f.seek(index*2016*80)
        h = f.write(chunk)
        f.close()
        self.set_local_height()

    def truncate_headers(self, height):
        filename = self.path()
        f = open(filename,'rb+')
        f.truncate(height*80)
        f.close()
        self.set_local_height()

    def erase_chunk(self, index):
        filename = self.path()
        f = open(filename,'rb+')
        f.truncate(index*2016*80)
        f.close()
        self.set_local_height()

    def save_header(self, header):
        data = self.header_to_string(header).decode('hex')
        assert len(data) == 80
        height = header.get('block_height')
        filename = self.path()
        f = open(filename,'rb+')
        f.seek(height*80)
        h = f.write(data)
        f.close()
        self.set_local_height()


    def set_local_height(self):
        name = self.path()
        if os.path.exists(name):
            h = os.path.getsize(name)/80 - 1
            if self.local_height != h:
                self.local_height = h


    def read_header(self, block_height):
        name = self.path()
        if os.path.exists(name):
            f = open(name,'rb')
            f.seek(block_height*80)
            h = f.read(80)
            f.close()
            if len(h) == 80:
                h = self.header_from_string(h)
                return h

    def get_target(self, height, chain=None):
        if chain is None:
            chain = []  # Do not use mutables as default values!

        # if height < 120: return 0x1e0ffff0, 0x00000FFFF0000000000000000000000000000000000000000000000000000000
        if height < 120:
            return 0x1e0ffff0, max_target
        elif height >= dgw_start:
            return self.get_target_dgw(height, chain);
        elif height >= kgw_start:
            return self.KimotoGravityWell(height, chain, None); #

        # https://github.com/FundacionPesetacoin/Pesetacoin-0.9.1-Oficial/blob/9df921d230d3a45c0587e084568beea9f75033d2/src/main.cpp#L1285
        nTargetTimespan     = 2*60*60       #pesetacoin: every 4 hours
        nTargetTimespanNEW  = 60            #pesetacoin: every 1 minute
        nTargetSpacing      = 60            #pesetacoin: 1 minute
        nInterval           = nTargetTimespan / nTargetSpacing #120
        retargetTimespan    = nTargetTimespan
        retargetInterval    = nInterval

        blockstogoback = retargetInterval - 1
        if (height != retargetInterval):
            blockstogoback = retargetInterval

        latest_retarget_height = (height / retargetInterval) * retargetInterval
        #print 'latest_retarget_height', latest_retarget_height
        last_height  = latest_retarget_height - 1
        first_height = last_height - blockstogoback

        #print 'first height', first_height
        #print 'last height', last_height

        first = self.read_header(first_height)
        last  = self.read_header(last_height)

        #print 'first'
        #print first
        #print 'last'
        #print last

        if first is None:
            for h in chain:
                if h.get('block_height') == first_height:
                    first = h

        if last is None:
            for h in chain:
                if h.get('block_height') == last_height:
                    last = h

        nActualTimespan    = last.get('timestamp') - first.get('timestamp')
        nModulatedTimespan = nActualTimespan

	if (nActualTimespan < nTargetTimespan/4):
		nModulatedTimespan = nTargetTimespan;
	if (nActualTimespan > nTargetTimespan*4):
		nModulatedTimespan = nTargetTimespan * 4;

        bits = last.get('bits')

        #print 'before', hex(bits)
        #print 'nActualTimespan', nActualTimespan
        #print 'nTargetTimespan', nTargetTimespan
        #print 'retargetTimespan', retargetTimespan
        #print 'nModulatedTimespan', nModulatedTimespan

        return self.get_target_from_timespans(bits, nModulatedTimespan, retargetTimespan)

    def get_target_from_timespans(self, bits, nActualTimespan, nTargetTimespan):

        # convert to bignum
        MM = 256*256*256
        a = bits%MM
        if a < 0x8000:
            a *= 256
        target = (a) * pow(2, 8 * (bits/MM - 3))

        # new target
        new_target = min( max_target, cdiv(target * nActualTimespan, nTargetTimespan) )

        # convert it to bits
        c = ("%064X"%new_target)[2:]
        i = 31
        while c[0:2]=="00":
            c = c[2:]
            i -= 1

        c = int('0x'+c[0:6],16)
        if c >= 0x800000:
            c /= 256
            i += 1

        new_bits = c + MM * i

        #print 'new target: ', hex(new_target)
        return new_bits, new_target

    def request_header(self, i, h, queue):
        print_error("requesting header %d from %s"%(h, i.server))
        i.send_request({'method':'blockchain.block.get_header', 'params':[h]}, queue)

    def retrieve_request(self, queue):
        while True:
            try:
                # Original line
                #ir = queue.get(timeout=1) 
                # Pesetacoin Foundation tests
                ir = queue.get(timeout=300) 
            except Queue.Empty:
                print_error('blockchain: request timeout')
                continue
            i, r = ir
            result = r['result']
            return result

    def get_chain(self, interface, final_header):

        header = final_header
        chain = [ final_header ]
        requested_header = False
        queue = Queue.Queue()

        while self.is_running():

            if requested_header:
                header = self.retrieve_request(queue)
                if not header: return
                chain = [ header ] + chain
                requested_header = False

            height = header.get('block_height')
            previous_header = self.read_header(height -1)
            if not previous_header:
                self.request_header(interface, height - 1, queue)
                requested_header = True
                continue

            # verify that it connects to my chain
            prev_hash = self.hash_header(previous_header)
            if prev_hash != header.get('prev_block_hash'):
                print_error("reorg")
                # truncate headers file
                self.truncate_headers(height - 2)
                self.request_header(interface, height - 1, queue)
                requested_header = True
                continue

            else:
                # the chain is complete
                return chain


    def get_and_verify_chunks(self, i, header, height):

        queue = Queue.Queue()
        min_index = (self.local_height + 1)/2016
        max_index = (height + 1)/2016
        n = min_index
        while n < max_index + 1:
            print_error( "Requesting chunk:", n )
            # todo: pesetacoin get_auxblock_chunk after block 46000...?
            # todo: call blockchain.block.get_auxblock from verify_chunk instead?
            i.send_request({'method':'blockchain.block.get_chunk', 'params':[n]}, queue)
            r = self.retrieve_request(queue)

            #print 'chunk compressed length : ', len(r)
            r = zlib.decompress(r.decode('hex'))
            #print 'chunk uncompressed length : ', len(r)

            try:
                self.verify_chunk(n, r)
                n = n + 1
            except Exception:
                print traceback.format_exc()
                print_error('Verify chunk failed!')
                self.erase_chunk(n)
                n = n - 1
                if n < 0:
                    return False

        return True
    def get_target_dgw(self, block_height, chain=None):
        if chain is None:
            chain = []

        last = self.read_header(block_height-1)
        if last is None:
            for h in chain:
                if h.get('block_height') == block_height-1:
                    last = h
        # params
        BlockLastSolved = last
        BlockReading = last
        nActualTimespan = 0
        LastBlockTime = 0
        PastBlocksMin = 24
        PastBlocksMax = 24
        CountBlocks = 0
        PastDifficultyAverage = 0
        PastDifficultyAveragePrev = 0
        bnNum = 0
        target_spacing = 60            #pesetacoin: every 1 minute

        if BlockLastSolved is None or block_height-1 < PastBlocksMin:
            return target_to_bits(max_target), max_target
        for i in range(1, PastBlocksMax + 1):
            CountBlocks += 1
            
            if CountBlocks <= PastBlocksMin:
                if CountBlocks == 1:
                    PastDifficultyAverage = bits_to_target(BlockReading.get('bits'))
                else:
                    bnNum = bits_to_target(BlockReading.get('bits'))
                    PastDifficultyAverage = ((PastDifficultyAveragePrev * CountBlocks)+(bnNum)) / (CountBlocks + 1)
                PastDifficultyAveragePrev = PastDifficultyAverage

            if LastBlockTime > 0:
                Diff = (LastBlockTime - BlockReading.get('timestamp'))
                nActualTimespan += Diff
            LastBlockTime = BlockReading.get('timestamp')

            BlockReading = self.read_header((block_height-1) - CountBlocks)
            if BlockReading is None:
                for br in chain:
                    if br.get('block_height') == (block_height-1) - CountBlocks:
                        BlockReading = br

        bnNew = PastDifficultyAverage
        nTargetTimespan = CountBlocks * target_spacing

        nActualTimespan = max(nActualTimespan, nTargetTimespan/3)
        nActualTimespan = min(nActualTimespan, nTargetTimespan*3)

        # retarget
        bnNew *= nActualTimespan
        bnNew /= nTargetTimespan

        bnNew = min(bnNew, max_target)

        new_bits = target_to_bits(bnNew)
        return new_bits, bnNew
        
    def KimotoGravityWell(self, height, chain=[],data=None):    
        #print_msg ("height=",height,"chain=", chain, "data=", data)
        BlocksTargetSpacing         = 1 * 60; # 1 minute
        TimeDaySeconds              = 60 * 60 * 24;
        PastSecondsMin              = int(TimeDaySeconds * 0.01);
        PastSecondsMax              = int(TimeDaySeconds * 0.14);
        PastBlocksMin               = int(PastSecondsMin / BlocksTargetSpacing);
        PastBlocksMax               = int(PastSecondsMax / BlocksTargetSpacing);
        PastBlocksMass              = 0
        BlockReadingIndex           = height - 1
        BlockLastSolvedIndex        = height - 1
        TargetBlocksSpacingSeconds  = BlocksTargetSpacing
        PastRateAdjustmentRatio     = 1.0
        bnProofOfWorkLimit          = 0x00000FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
        LatestBlockTime             = 0

        last = self.read_header(BlockLastSolvedIndex)
        if last is None:
            for h in chain:
                if h.get('block_height') == BlockLastSolvedIndex:
                    last = h

        if (BlockLastSolvedIndex <= 0 or BlockLastSolvedIndex < PastBlocksMin or last is None):
            new_target = bnProofOfWorkLimit
            new_bits = self.convbits(new_target)
            return new_bits, new_target

        LatestBlockTime = last.get('timestamp')

        for i in xrange(1,int(PastBlocksMax)+1):
            if (PastBlocksMax > 0 and i > PastBlocksMax):
                break
            PastBlocksMass = PastBlocksMass + 1

            reading = self.read_header(BlockReadingIndex)
            if reading is None:
                for h in chain:
                    if h.get('block_height') == BlockReadingIndex:
                        reading = h

            if (i == 1):
                PastDifficultyAverage=self.convbignum(reading.get('bits'))

            else:
                PastDifficultyAverage= int(self.convbignum(reading.get('bits')) - PastDifficultyAveragePrev) / int(i) + PastDifficultyAveragePrev
            PastDifficultyAveragePrev = PastDifficultyAverage

            if (BlockReadingIndex > kgw_fix and LatestBlockTime < reading.get('timestamp')):
                LatestBlockTime = reading.get('timestamp')

            PastRateActualSeconds = LatestBlockTime - reading.get('timestamp')

            PastRateTargetSeconds = TargetBlocksSpacingSeconds * PastBlocksMass
            PastRateAdjustmentRatio = 1.0
            if (PastRateActualSeconds < 1 and BlockReadingIndex > kgw_fix):
                PastRateActualSeconds = 1
            elif(PastRateActualSeconds < 0):
                PastRateActualSeconds = 0

            if (PastRateActualSeconds != 0 and PastRateTargetSeconds != 0):
                PastRateAdjustmentRatio   = float(PastRateTargetSeconds) / float(PastRateActualSeconds)
        
            EventHorizonDeviation       = 1 + (0.7084 * pow(float(PastBlocksMass)/28.2, -1.228))
            EventHorizonDeviationFast   = EventHorizonDeviation
            EventHorizonDeviationSlow   = float(1) / float(EventHorizonDeviation)
                
            if (PastBlocksMass >= PastBlocksMin):
                if (PastRateAdjustmentRatio <= EventHorizonDeviationSlow or PastRateAdjustmentRatio >= EventHorizonDeviationFast):
                    break

            BlockReadingIndex = BlockReadingIndex - 1
                     
            if (BlockReadingIndex < 1):
                break
        bnNew   = PastDifficultyAverage
        if (PastRateActualSeconds != 0 and PastRateTargetSeconds != 0):
            bnNew = bnNew * PastRateActualSeconds
            bnNew = bnNew / PastRateTargetSeconds
			
        if (bnNew > bnProofOfWorkLimit):
            bnNew = bnProofOfWorkLimit

        # new target
        new_target = bnNew
        new_bits = self.convbits(new_target)
		
        return new_bits, new_target

    def convbignum(self, bits):
        # convert to bignum
        return (bits & 0xffffff) *(1<<( 8 * ((bits>>24) - 3)))

# START electrum-peseta-server
# the following code was copied from the server's utils.py file
def tx_from_string(s):
    vds = BCDataStream()
    vds.write(s)
    #vds.write(raw.decode('hex'))
    d = {}
    d['version'] = vds.read_int32()
    n_vin = vds.read_compact_size()
    d['vin'] = []
    for i in xrange(n_vin):
        txin = {}
        # dirty hack: add outpoint structure to get correct txid later
        outpoint_pos = vds.read_cursor
        txin['coinbase'] = vds.read_bytes(vds.read_compact_size()).encode('hex')
        txin['sequence'] = vds.read_uint32()
        d['vin'].append(txin)
    n_vout = vds.read_compact_size()
    d['vout'] = []
    for i in xrange(n_vout):
        txout = {}
        txout['value'] = vds.read_int64()
        txout['scriptPubKey'] = vds.read_bytes(vds.read_compact_size()).encode('hex')
        d['vout'].append(txout)
    d['lockTime'] = vds.read_uint32()

    # compute txid
    # dirty hack to insert coinbase outpoint structure before hashing
    raw = s[0:outpoint_pos]
    COINBASE_OP = '0' * 64 + 'F' * 8
    raw += (COINBASE_OP).decode('hex')
    raw += s[outpoint_pos:vds.read_cursor]

    d['txid'] = Hash(raw)[::-1].encode('hex')

    return d, s[vds.read_cursor:] # +1?

def merkle_branch_from_string(s):
    vds = BCDataStream()
    vds.write(s)
    #vds.write(raw.decode('hex'))
    hashes = []
    n_hashes = vds.read_compact_size()
    for i in xrange(n_hashes):
        _hash = vds.read_bytes(32)
        hashes.append(hash_encode(_hash))
    index = vds.read_int32()
    return hashes, index, s[vds.read_cursor:]

def hex_to_int(s):
    return int('0x' + s[::-1].encode('hex'), 16)


def header_from_string(s):
    res = {
        'version': hex_to_int(s[0:4]),
        'prev_block_hash': hash_encode(s[4:36]),
        'merkle_root': hash_encode(s[36:68]),
        'timestamp': hex_to_int(s[68:72]),
        'bits': hex_to_int(s[72:76]),
        'nonce': hex_to_int(s[76:80]),
    }

    if (len(s) > 80):
        res['auxpow_offset'] = hex_to_int(s[80:84])
        res['auxpow_length'] = hex_to_int(s[84:88])

    return res
