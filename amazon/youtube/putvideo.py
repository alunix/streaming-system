#!/usr/bin/python

"""Uploads videos in a directory to Youtube's SFTP server."""

import os
import libssh2
import logging.config
import sys
import socket
import time

HOSTPORT = ("googlefosssydney.xfer.youtube.com", 22)
USERNAME = os.environ['YOUTUBE_USER']
PRIVATE_KEY = os.path.expanduser("~/.ssh/youtube")
PASSWORD = os.environ['YOUTUBE_PASSWORD']

def getfiles(path):
  files = {}
  for filename in os.listdir(path):
    if not filename.endswith('.flv'):
      continue
    files[filename] = os.stat(os.path.join(path, filename)).st_size
  return files


def guess_event(date):
  # If Friday it's probably SLUG
  if date.tm_wday == 4:
    return {'name': 'Sydney Linux User Group',
            'shortname': 'SLUG',
            'tags': 'Linux, open source, free software, foss, oss',
            }

  # If it's a Thursday it could be SyPy or FP Syd
  if date.tm_wday == 3:
    # First Thursday is SyPy
    if date.tm_mday < 14:
      return {'name': 'Sydney Python User Group',
              'shortname': 'SyPy',
              'tags': 'Python, programming',
              }
    # Probably FP-Syd
    else:
      return {'name': 'Functional Programming Sydney',
              'shortname': 'FP-Syd',
              'tags': 'functional, programming',
              }

  return {'name': 'Unknown Tech Talk',
          'shortname': 'Unknown Tech Talk',
          'tags': '',
          }


def sftp_listdir(sftp, dirname):
  handle = sftp.open_dir(dirname)
  if not handle:
    return

  details = {}
  while True:
    d = sftp.read_dir(handle)
    if not d:
      break
    childname, stats = d
    if childname in ('.', '..'):
      continue
    details[childname] = stats
  return details


def sftp_put(sftp, infilename, outfilename, progress):
  infile = file(infilename, 'rb')
  size = os.stat(infilename).st_size
  outfile = sftp.open(outfilename, 'wb')

  uploaded = 0
  while True:
    block = infile.read(1024*1024)
    if not block:
      break

    sftp.write(outfile, block)

    uploaded += len(block)
    progress(uploaded, size)
  infile.close()
  sftp.close(outfile)


def sftp_write(sftp, filename, data):
  handle = sftp.open(filename, 'wb')
  sftp.write(handle, data)
  sftp.close(handle)


PREVIOUS=None
def progress(b, total):
  global PREVIOUS
  next = "%5.2f%%" % (b*1.0/total*100)
  if next == PREVIOUS:
    return
  print next, '%10.2fmb' % (b/1e6)
  PREVIOUS = next


def main(argv):
  logging.config.fileConfig(open("logging.ini"))
  path = argv[0]

  files_start = getfiles(path)
  time.sleep(0.1)
  files_end = getfiles(path)

  # Find the files which haven't changed size.
  unchanged = {}
  for filename, start_size in files_start.iteritems():
    try:
      end_size = files_end[filename]
    except KeyError:
      continue

    if start_size == end_size:
      unchanged[filename] = end_size

  print "Found %s files to possibly upload (%s changing)" % (
      len(unchanged), len(files_end)-len(unchanged))

  # Connect to youtube's SFTP server
  sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
  sock.connect(HOSTPORT)
  sock.setblocking(1)

  session = libssh2.Session()
  session.startup(sock)
  logging.info('%r %r %r', USERNAME, PRIVATE_KEY+'.pub', PRIVATE_KEY)
  session.userauth_publickey_fromfile(
      USERNAME.lower(), PRIVATE_KEY+'.pub', PRIVATE_KEY, '')

  # open a SFTP channel
  sftp = session.sftp()

  sftp_dirs = {}

  for dirname, stats in sftp_listdir(sftp, '/').items():
    files = {}
    for filename, stats in sftp_listdir(sftp, dirname).items():
      files[filename] = stats[0]
    sftp_dirs[dirname] = files

  for filename, size in unchanged.iteritems():
    # Video files will be gigabytes in size
    #if size < 1e9:
    #  print filename, "File too small", size
    #  continue

    # Has the file already been uploaded?
    basename = filename[:filename.rfind('.')]
    if os.path.exists(basename+'.uploaded'):
      continue

    # Create the directory
    if basename not in sftp_dirs:
      sftp.mkdir(basename)
      sftp_dirs[basename] = {}

    files = sftp_dirs[basename]

    # Check if the we have a completion status report
    if filename+".status" in files:
      print filename, "already uploaded and processed."
      continue

    if "delivery.complete" in files:
      print filename, "already uploaded and awaiting processing."
      continue

    # Upload the actual video
    upload = False
    if filename not in files and filename+".status" not in files:
      upload = True

    elif files[filename] != size:
      upload = True

    # Create the metadata
    if basename+".xml" not in files:
      datestr = basename[basename.rfind('.')+1:]
      date = time.strptime(datestr, "%Y%m%d-%H%M%S")

      xmlfilename = basename+".xml"

      info = guess_event(date)
      info['date'] = datestr
      info['humandate'] = time.strftime('%A, %d %B %Y', date)
      info['filename'] = filename
      info['username'] = USERNAME
      info['password'] = PASSWORD
      print "Guessing the event is", info['shortname']

      sftp_write(sftp, basename+'/'+xmlfilename, """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
 xmlns:media="http://search.yahoo.com/mrss"
 xmlns:yt="http://www.youtube.com/schemas/yt/0.2">
 <channel>
   <yt:notification_email>tansell@google.com</yt:notification_email>
   <yt:account>
     <yt:username>%(username)s</yt:username>
     <yt:password>%(password)s</yt:password>
   </yt:account>
   <yt:owner_name>%(username)s</yt:owner_name>

   <item>
     <yt:action>Insert</yt:action>
     <media:title>%(shortname)s - %(date)s</media:title>
     <media:content url="file://%(filename)s" >
       <media:description type="plain">Talk at %(name)s given on %(humandate)s</media:description>
       <media:keywords>open source, google, sydney, %(tags)s</media:keywords>
       <media:category>Science &amp; Technology</media:category>
       <media:rating scheme="urn:simple">nonadult</media:rating>
     </media:content>
     <yt:language>en</yt:language>
     <yt:date_recorded>2005-08-01</yt:date_recorded>

     <yt:location>
       <yt:country>AU</yt:country>
       <yt:zip_code>NSW 2009</yt:zip_code>
       <yt:location_text>Pyrmont</yt:location_text>
     </yt:location>

     <yt:start_time>2007-07-07T07:07:07</yt:start_time> <!-- A date
in the past -->

     <yt:community>
       <yt:allow_comments>Always</yt:allow_comments>
       <yt:allow_responses>Never</yt:allow_responses>
       <yt:allow_ratings>true</yt:allow_ratings>
       <yt:allow_embedding>true</yt:allow_embedding>
     </yt:community>
   </item>
</channel>
""" % info)
      print xmlfilename, "uploaded metadata"

    if upload:
      print filename, "uploading."
      sftp_put(sftp, path+'/'+filename, basename+'/'+filename, progress)
      print filename, " uploaded."

    if success:
      deliveryname = "delivery.complete"

      print deliveryname, "uploading completion file"
      sftp_write(sftp, basename+'/'+deliveryname, '')
      print deliveryname, "uploading completion file"

  print 'Upload done.'


if __name__ == '__main__':
  main(sys.argv[1:])