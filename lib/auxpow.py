# https://github.com/kR105/i0coin/compare/bitcoin:master...master#diff-d3b948fe89a5d012a7eaeea8f25d7c42R1
import string
import btcutils

BLOCK_VERSION_CHAIN_START = (1 << 16)

def get_our_chain_id():
    #https://github.com/pesetacoin/pesetacoin/blob/65228644e10328172e9fa3ebe64251983e1153b3/src/core.h#L38
    return 0x0047 #pesetacoin

def get_chain_id(header):
    return header['version'] / BLOCK_VERSION_CHAIN_START

def check_merkle_branch(hash, merkle_branch, index):
    return btcutils.check_merkle_branch(hash, merkle_branch, index)

# https://github.com/kR105/i0coin/compare/bitcoin:master...master#diff-610df86e65fce009eb271c2a4f7394ccR262
def calc_merkle_index(chain_id, nonce, merkle_size):
    #rand = nonce
    #rand = (rand * 1103515245 + 12345) & 0xffffffff
    #rand += chain_id
    #rand = (rand * 1103515245 + 12345) & 0xffffffff

    # https://github.com/FundacionPesetacoin/Pesetacoin-0.9.1-Oficial/blob/9df921d230d3a45c0587e084568beea9f75033d2/src/auxpow.cpp#L84
    rand = nonce
    rand = rand * 1103515245 + 12345
    #rand = rand * 1103361204 + 166386
    rand += chain_id
    rand = rand * 1103515245 + 12345
    #rand = rand * 1103361204 + 166386

    return rand % merkle_size

def verify(auxhash, chain_id, auxpow):
    parent_block = auxpow['parent_block']
    coinbase = auxpow['coinbasetx']
    coinbase_hash = coinbase['txid']

    chain_merkle_branch = auxpow['chainMerkleBranch']
    chain_index = auxpow['chainIndex']

    coinbase_merkle_branch = auxpow['coinbaseMerkleBranch']
    coinbase_index = auxpow['coinbaseIndex']

    #if (get_chain_id(parent_block) == chain_id)
    #  return error("Aux POW parent has our chain ID");

    if (get_chain_id(parent_block) == chain_id):
        print 'Aux POW parent has our chain ID'
        return False

    #// Check that the chain merkle root is in the coinbase
    #uint256 nRootHash = CBlock::CheckMerkleBranch(hashAuxBlock, vChainMerkleBranch, nChainIndex);
    #vector<unsigned char> vchRootHash(nRootHash.begin(), nRootHash.end());
    #std::reverse(vchRootHash.begin(), vchRootHash.end()); // correct endian

    # Check that the chain merkle root is in the coinbase
    root_hash = check_merkle_branch(auxhash, chain_merkle_branch, chain_index)

    # Check that we are in the parent block merkle tree
    # if (CBlock::CheckMerkleBranch(GetHash(), vMerkleBranch, nIndex) != parentBlock.hashMerkleRoot)
    #    return error("Aux POW merkle root incorrect");
    if (check_merkle_branch(coinbase_hash, coinbase_merkle_branch, coinbase_index) != parent_block['merkle_root']):
        print 'Aux POW merkle root incorrect'
        return False

    #// Check that the same work is not submitted twice to our chain.
    #//

    #CScript::const_iterator pcHead =
        #std::search(script.begin(), script.end(), UBEGIN(pchMergedMiningHeader), UEND(pchMergedMiningHeader));

    #CScript::const_iterator pc =
        #std::search(script.begin(), script.end(), vchRootHash.begin(), vchRootHash.end());

    #if (pc == script.end())
        #return error("Aux POW missing chain merkle root in parent coinbase");

    script = coinbase['vin'][0]['coinbase']
    pos = string.find(script, root_hash)

    # todo: if pos == -1 ??
    if pos == -1:
        print 'Aux POW missing chain merkle root in parent coinbase'
        return False

    #todo: make sure only submitted once
    #if (pcHead != script.end())
    #{
        #// Enforce only one chain merkle root by checking that a single instance of the merged
        #// mining header exists just before.
        #if (script.end() != std::search(pcHead + 1, script.end(), UBEGIN(pchMergedMiningHeader), UEND(pchMergedMiningHeader)))
            #return error("Multiple merged mining headers in coinbase");
        #if (pcHead + sizeof(pchMergedMiningHeader) != pc)
            #return error("Merged mining header is not just before chain merkle root");
    #}
    #else
    #{
        #// For backward compatibility.
        #// Enforce only one chain merkle root by checking that it starts early in the coinbase.
        #// 8-12 bytes are enough to encode extraNonce and nBits.
        #if (pc - script.begin() > 20)
            #return error("Aux POW chain merkle root must start in the first 20 bytes of the parent coinbase");
    #}


    #// Ensure we are at a deterministic point in the merkle leaves by hashing
    #// a nonce and our chain ID and comparing to the index.
    #pc += vchRootHash.size();
    #if (script.end() - pc < 8)
        #return error("Aux POW missing chain merkle tree size and nonce in parent coinbase");

    pos = pos + len(root_hash)
    if (len(script) - pos < 8):
        print 'Aux POW missing chain merkle tree size and nonce in parent coinbase'
        return false

     #int nSize;
    #memcpy(&nSize, &pc[0], 4);
    #if (nSize != (1 << vChainMerkleBranch.size()))
        #return error("Aux POW merkle branch size does not match parent coinbase");

    def hex_to_int(s):
        s = s.decode('hex')[::-1].encode('hex')
        return int(s, 16)

    size = hex_to_int(script[pos:pos+8])
    nonce = hex_to_int(script[pos+8:pos+16])

    #print 'size',size
    #print 'nonce',nonce
    #print '(1 << len(chain_merkle_branch)))', (1 << len(chain_merkle_branch))
    #size = hex_to_int(script[pos:pos+4])
    #nonce = hex_to_int(script[pos+4:pos+8])

    if (size != (1 << len(chain_merkle_branch))):
        print 'Aux POW merkle branch size does not match parent coinbase'
        return False

    #int nNonce;
    #memcpy(&nNonce, &pc[4], 4);
    #// Choose a pseudo-random slot in the chain merkle tree
    #// but have it be fixed for a size/nonce/chain combination.
    #//
    #// This prevents the same work from being used twice for the
    #// same chain while reducing the chance that two chains clash
    #// for the same slot.
    #unsigned int rand = nNonce;
    #rand = rand * 1103515245 + 12345;
    #rand += nChainID;
    #rand = rand * 1103515245 + 12345;

    #if (nChainIndex != (rand % nSize))
        #return error("Aux POW wrong index");

    index = calc_merkle_index(chain_id, nonce, size)
    #print 'index', index

    if (chain_index != index):
        print 'Aux POW wrong index : $chain_index='+str(chain_index)+', $index='+str(index)
        return False

    return True
