"""Atomic queue operations, including ownership checks inside Redis."""

CHECK_LEASE = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
    return redis.error_reply('DISPLAY_LEASE_LOST')
end
"""

CHECK_CLAIM = CHECK_LEASE + """
if redis.call('HGET', KEYS[2], 'payload') ~= ARGV[2] then
    return redis.error_reply('DISPLAY_CLAIM_CHANGED')
end
"""

# A single display lease allows a single in-flight record. Recover it before
# taking newer work. Store the payload before removing it from the pending list.
CLAIM = CHECK_LEASE + """
local payload = redis.call('HGET', KEYS[2], 'payload')
local recovered = 1
if not payload then
    payload = redis.call('LINDEX', KEYS[3], 0)
    if not payload then return nil end
    redis.call('HSET', KEYS[2], 'payload', payload,
        'content_attempts', 0, 'transition_attempts', 0)
    redis.call('LPOP', KEYS[3])
    recovered = 0
end
return {payload, recovered,
    redis.call('HGET', KEYS[2], 'content_attempts'),
    redis.call('HGET', KEYS[2], 'transition_attempts')}
"""

START_ATTEMPT = CHECK_CLAIM + """
local attempts = tonumber(redis.call('HGET', KEYS[2], ARGV[3]) or '0')
if attempts >= tonumber(ARGV[4]) then return 0 end
return redis.call('HINCRBY', KEYS[2], ARGV[3], 1)
"""

# Record display state and flight success in the same operation that acknowledges
# the claim. An old worker cannot acknowledge or overwrite a successor's state.
ACKNOWLEDGE = CHECK_CLAIM + """
redis.call('HSET', KEYS[3], 'state', ARGV[3], 'source', ARGV[4],
    'transition', ARGV[5], 'message_id', ARGV[6])
if ARGV[7] ~= '' then
    redis.call('SET', KEYS[5], '1', 'EX', 3600)
    if redis.call('GET', KEYS[4]) == ARGV[6] then
        redis.call('DEL', KEYS[4])
    end
end
redis.call('DEL', KEYS[2])
return 1
"""

FAIL = CHECK_CLAIM + """
local failure = cjson.encode({payload = ARGV[2], error = ARGV[3],
    failed_at = ARGV[4], message_id = ARGV[5], source = ARGV[6],
    content_attempts = tonumber(redis.call('HGET', KEYS[2], 'content_attempts')),
    transition_attempts = tonumber(redis.call('HGET', KEYS[2], 'transition_attempts'))})
redis.call('RPUSH', KEYS[3], failure)
if ARGV[7] ~= '' and redis.call('GET', KEYS[4]) == ARGV[5] then
    redis.call('DEL', KEYS[4])
end
redis.call('DEL', KEYS[2])
return 1
"""

ENQUEUE_FLIGHT = """
if redis.call('EXISTS', KEYS[2], KEYS[3]) > 0 then return 0 end
redis.call('RPUSH', KEYS[1], ARGV[1])
redis.call('SET', KEYS[2], ARGV[2])
return 1
"""
