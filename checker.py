#!/usr/bin/env python

import os
import random
import signal
import socket
import string
import sys
import telnetlib
import threading
import time
import urllib
import urlparse

# Grading Details
GET_TEST_SCORE = 15
CACHE_TEST_SCORE = 20
POST_TEST_SCORE = 5
EXTRA_F_TEST_SCORE = 10

# simple_get_urls - The list of URLs to compare between the proxy
# and a direct connection.
#
# You can create additional automated tests for your proxy by
# adding URLs to this array.
# Those will wight 4.5 points of your grade.
# 
simple_get_urls = ['http://elf.cs.pub.ro/',
                   'http://elf.cs.pub.ro/pp/_media/wiki/logo.png',
                   'http://protocoale.dorinelfilip.info/lorem-ipsum.html'
                   ]

# Examples of bad requests (not implemented yet)
bad_requests = ['UNKNOWN http://www.google.ro HTTP/1.0'
                'GET / HTTP/1.0']

post_lengths = [5, 15, 100]

post_url = 'http://protocoale.dorinelfilip.info/post.php'
cache_test_url = 'http://protocoale.dorinelfilip.info/cache.php'
cache_reset_url = 'http://protocoale.dorinelfilip.info/reset.php'
extra_fields_url = 'http://protocoale.dorinelfilip.info/extra.php'

# timeout_secs - Individual tests will be killed if they do not
# complete within this span of time.
timeout_secs = 30.0


def main():
    global simple_get_urls
    try:
        proxy_bin = sys.argv[1]
    except IndexError:
        usage()
        sys.exit(2)
    try:
        port = sys.argv[2]
    except IndexError:
        port = str(random.randint(1025, 49151))

    print 'Binary: %s' % proxy_bin
    print 'Running on port %s' % port

    # Start the proxy running in the background
    cid = os.spawnl(os.P_NOWAIT, proxy_bin, proxy_bin, port)
    # Give the proxy time to start up and start listening on the port
    time.sleep(2)

    simple_pass_count = 0
    print 'Running Simple Tests:'
    for url in simple_get_urls:
        print '### Testing GET: ' + url
        passed = run_test(test_get_url, (url, port), cid)
        if not live_process(cid):
            print '!!!Proxy process experienced abnormal termination during test- restarting proxy!'
            (cid, port) = restart_proxy(proxy_bin, port)
            passed = False

        if passed:
            print '%s: [PASSED]\n' % url
            simple_pass_count += 1
        else:
            print '%s: [FAILED]\n' % url

    print '### Testing Cache Implementation'
    passed = run_test(test_cache, (port), cid)
    if not live_process(cid):
        print '!!!Proxy process experienced abnormal termination during test- restarting proxy!'
        (cid, port) = restart_proxy(proxy_bin, port)
        passed = False

    if passed:
        print 'Cache [PASSED]\n'
    else:
        print 'Cache [FAILED]\n'

    cache_passed = 1 if passed else 0

    print '### Testing Extra Request Fields Forwarding'
    passed = run_test(test_extra_fields, (port), cid)
    if not live_process(cid):
        print '!!!Proxy process experienced abnormal termination during test- restarting proxy!'
        (cid, port) = restart_proxy(proxy_bin, port)
        passed = False

    if passed:
        print 'Extra Fields [PASSED]\n'
    else:
        print 'Extra Fields [FAILED]\n'

    extra_fields_passed = 1 if passed else 0

    post_pass_count = 0
    print 'Testing POST Request(s)'
    for length in post_lengths:
        print '### Testing post with token size = ' + str(length)
        passed = run_test(test_post, (length, port), cid)
        if not live_process(cid):
            print '!!!Proxy process experienced abnormal termination during test- restarting proxy!'
            (cid, port) = restart_proxy(proxy_bin, port)
            passed = False

        if passed:
            print 'POST %d: [PASSED]\n' % length
            post_pass_count += 1
        else:
            print 'POST %d: [FAILED]\n' % length

    # Cleanup
    terminate(cid)

    print 'Summary: '
    print '\t%d of %d GET tests passed [%d points/test]' % (simple_pass_count, len(simple_get_urls), GET_TEST_SCORE)
    print '\t%d of %d POST tests passed [%d points/test]' % (post_pass_count, len(post_lengths), POST_TEST_SCORE)
    if cache_passed:
        print '\tCache works correctly :) [%d points]' % CACHE_TEST_SCORE
    else:
        print '\tCache doesn\'t work :( [-%d points]' % CACHE_TEST_SCORE

    if extra_fields_passed:
        print '\tExtra fields forwarding is done :) [%d points]' % EXTRA_F_TEST_SCORE
    else:
        print '\tExtra request fields forwarding ins missing :( [-%d points]' % EXTRA_F_TEST_SCORE

    student_grade = simple_pass_count * GET_TEST_SCORE + \
                    cache_passed * CACHE_TEST_SCORE + \
                    post_pass_count * POST_TEST_SCORE +\
                    extra_fields_passed * EXTRA_F_TEST_SCORE

    max_grade = len(simple_get_urls) * GET_TEST_SCORE \
                + len(post_lengths) * POST_TEST_SCORE \
                + CACHE_TEST_SCORE + EXTRA_F_TEST_SCORE

    print 'Your grade is: %d of %d' % (student_grade, max_grade)


def usage():
    print "Usage: proxy_grader.py path/to/proxy/binary port"
    print "Omit the port argument for a randomly generated port."


def run_test(test, args, childid):
    '''
    Run a single test function, monitoring its execution with a timer thread.

    * test: A function to execute.  Should take a tuple as its sole 
    argument and return True for a passed test, and False otherwise.
    * args: Tuple that contains arguments to the test function
    * childid: Process ID of the running proxy

    The amount of time that the monitor waits before killing
    the proxy process can be set by changing timeout_secs at the top of this 
    file.
    
    Returns True for a passed test, False otherwise.
    '''
    monitor = threading.Timer(timeout_secs, do_timeout, [childid])
    monitor.start()
    if not test(args):
        passed = False
    else:
        passed = True

    monitor.cancel()
    return passed


def get_rand_string(len):
    return ''.join(
        random.choice(string.ascii_uppercase + string.digits)
        for _ in range(len))


def test_post(argtuple):
    (token_length, port) = argtuple
    url = post_url

    token = get_rand_string(token_length)
    check = token[::-1]
    params = {'token': token, 'check': check}

    # Retrieve via proxy
    try:
        proxy_data = post_by_proxy('localhost', port, url, params)
    except socket.error:
        print '!!!! Socket error while attempting to talk to proxy!'
        return False

    # Retrieve directly
    (host, hostport, path) = parse_url(url)
    direct_data = post_direct(host, hostport, path, params)

    # It should be the same
    if not compare_results(proxy_data, direct_data):
        return False

    return True


def test_get_url(argtuple):
    '''
    Compare proxy output to the output from a direct server transaction.
    
    A simple sample test: download a web page via the proxy, and then fetch the 
    same page directly from the server.  Compare the two pages for any
    differences, ignoring the Date header field if it is set.
    
    Argument tuples is in the form (url, port), where url is the URL to open, and
    port is the port the proxy is running on.
    '''
    (url, port) = argtuple
    (host, hostport, full_url) = parse_url(url)

    # Retrieve via proxy
    try:
        proxy_data = get_by_proxy('localhost', port, url)
    except socket.error:
        print '!!!! Socket error while attempting to talk to proxy!'
        return False

    # Retrieve directly
    direct_data = get_direct(host, hostport, full_url)

    return compare_results(proxy_data, direct_data)


def test_extra_fields(argtuple):
    '''
    Tests if extra HTTP request fields are forwarded correctly.
    '''
    port = argtuple
    url = extra_fields_url
    (host, hostport, full_url) = parse_url(url)

    # Retrieve via proxy
    try:
        proxy_data = get_by_proxy('localhost', port, url, True)
    except socket.error:
        print '!!!! Socket error while attempting to talk to proxy!'
        return False

    # Retrieve directly
    direct_data = get_direct(host, hostport, full_url, True)

    return compare_results(proxy_data, direct_data)


def compare_results(proxy_data, direct_data):
    if len(proxy_data) != len(direct_data):
        print "Proxy answer has different number of lines."
        return False

    passed = True
    for (proxy, direct) in zip(proxy_data, direct_data):
        if proxy != direct \
                and not (proxy.startswith('Date') and direct.startswith('Date')) \
                and not (proxy.startswith('Expires') and direct.startswith('Expires')) \
                and not (proxy.startswith('Set-Cookie') and direct.startswith('Set-Cookie')):
            print 'Proxy:\t%s' % proxy
            print 'Direct:\t%s' % direct
            passed = False

    return passed


def parse_url(url):
    url_data = urlparse.urlparse(url)
    try:
        (host, hostport) = url_data[1].split(':')
    except ValueError:
        host = url_data[1]
        hostport = 80

    return (host, hostport, url)


def test_cache(argtuple):
    (port) = argtuple
    encoded_params = '?' + urllib.urlencode({'token': get_rand_string(20)});

    url = cache_test_url + encoded_params
    reset_url = cache_reset_url + encoded_params

    # Retrieve via proxy
    try:
        proxy_data = get_by_proxy('localhost', port, url)
    except socket.error:
        print '!!!! Socket error while attempting to talk to proxy!'
        return False

    # Retrieve directly
    (host, hostport, path) = parse_url(url)
    direct_data = get_direct(host, hostport, path)

    # It should be the same, since the server did not change the content
    if not compare_results(proxy_data, direct_data):
        return False

    # Ask the server to change
    (reset_host, reset_port, reset_path) = parse_url(reset_url)
    res = get_direct(reset_host, reset_port, reset_path)

    # Retrieve something that is not our page
    try:
        proxy_data = get_by_proxy('localhost', port, simple_get_urls[0])
    except socket.error:
        print '!!!! Socket error while attempting to talk to proxy!'
        return False

    # Retrieve via proxy (once more)
    try:
        proxy_data = get_by_proxy('localhost', port, url)
    except socket.error:
        print '!!!! Socket error while attempting to talk to proxy!'
        return False

    # It should stay unchanged
    return compare_results(proxy_data, direct_data)


def get_direct(host, port, url, extra_fields=False):
    '''Retrieve a URL using direct HTTP/1.0 GET.'''
    if not extra_fields:
        getstring = 'GET %s HTTP/1.0\r\nConnection: close\r\n\r\n'
    else:
        getstring = 'GET %s HTTP/1.0\r\n' + \
        'Referer: http://cs.pub.ro/\r\n' + \
        'User-Agent: curl/7.47.0\r\n' + \
        'Connection: close\r\n\r\n'
    data = http_exchange(host, port, getstring % (url))
    return data.split('\n')


def get_by_proxy(host, port, url, extra_fields=False):
    '''Retrieve a URL using proxy HTTP/1.0 GET.'''
    if not extra_fields:
        getstring = 'GET %s HTTP/1.0\r\nConnection: close\r\n\r\n'
    else:
        getstring = 'GET %s HTTP/1.0\r\n' + \
        'Referer: http://cs.pub.ro/\r\n' + \
        'User-Agent: curl/7.47.0\r\n' + \
        'Connection: close\r\n\r\n'
    data = http_exchange(host, port, getstring % url)
    return data.split('\n')


def __get_POST_request_string(url, params):
    params_encoded = urllib.urlencode(params)
    content_length = len(params_encoded)

    post_template = \
        'POST %s HTTP/1.0\r\n' \
        'Content-length: %d\r\n' \
        'Content-Type: application/x-www-form-urlencoded\r\n' \
        'Connection: close\r\n' \
        '\r\n' \
        '%s'

    result = post_template % (url, content_length, params_encoded)
    return result


def post_direct(host, port, url, params):
    '''Hit an URL using direct HTTP/1.0 POST.'''
    data = http_exchange(host, port, __get_POST_request_string(url, params))
    return data.split('\n')


def post_by_proxy(host, port, url, params):
    '''Hit an URL using proxy HTTP/1.0 POST.'''
    data = http_exchange(host, port, __get_POST_request_string(url, params))
    return data.split('\n')


def http_exchange(host, port, data):
    conn = telnetlib.Telnet()
    conn.open(host, port)
    conn.write(data)
    ret_data = conn.read_all()
    conn.close()
    return ret_data


def live_process(pid):
    '''Check that a process is still running.'''
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def do_timeout(id):
    '''Callback function run by the monitor threads to kill a long-running operation.'''
    print '!!!! Proxy transaction timed out after %d seconds' % timeout_secs
    terminate(id)


def terminate(id):
    '''Stops and cleans up a running child process.'''
    assert (live_process(id))
    os.kill(id, signal.SIGINT)
    os.kill(id, signal.SIGKILL)
    try:
        os.waitpid(id, 0)
    except OSError:
        pass


def restart_proxy(binary, oldport):
    '''Restart the proxy on a new port number.'''
    newport = str(int(oldport) + 1)
    cid = os.spawnl(os.P_NOWAIT, binary, binary, newport)
    time.sleep(3)
    return (cid, newport)


if __name__ == '__main__':
    main()

