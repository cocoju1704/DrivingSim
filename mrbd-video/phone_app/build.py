#!/usr/bin/env python
"""
NDRT 영상 (phone app): build the APK without Gradle (the Android SDK's aapt2, d8, zipalign, apksigner
and a JDK), install it on the phone on USB, and copy the NDRT videos into the app's folder.

    python build.py                 build -> build/ndrt-video.apk
    python build.py --install       build, install on the USB phone (adb), start it
    python build.py --install --videos     also copy ../media/*.mp4 (the sets' NDRT clips) to the phone
    python build.py --videos-only   only copy the videos (those not there yet, or of another size);
                                    the phone's videos that are not in ../media/ are deleted from it

Finds the SDK in ANDROID_HOME / %LOCALAPPDATA%\\Android\\Sdk and a JDK 17+ in JAVA_HOME / ~/.jdks.
Signs with the Android debug key (~/.android/debug.keystore; made if missing).
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, 'build')
PACKAGE = 'com.drivingsim.ndrtvideo'
MIN_SDK, TARGET_SDK = 24, 34
VIDEO_DIR = os.path.join(os.path.dirname(HERE), 'media')   # mrbd-video/media/*.mp4: the sets' clips
PHONE_DIR = '/sdcard/Android/data/%s/files/Movies' % PACKAGE


def find_sdk():
    for base in (os.environ.get('ANDROID_HOME'), os.environ.get('ANDROID_SDK_ROOT'),
                 os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Android', 'Sdk')):
        if base and glob.glob(os.path.join(base, 'build-tools', '*', 'd8*')):
            return base
    sys.exit('Android SDK (build-tools) not found: set ANDROID_HOME')


def newest(paths):
    def key(p):
        try:
            return [int(x) for x in os.path.basename(p.rstrip('/\\')).replace('android-', '').split('.')]
        except ValueError:
            return [0]
    return sorted(paths, key=key)[-1]


def find_jdk():
    candidates = [os.environ.get('JAVA_HOME', '')] + sorted(glob.glob(os.path.expanduser('~/.jdks/*')), reverse=True) \
        + glob.glob(r'C:\Program Files\Android\Android Studio\jbr') + glob.glob(r'C:\Program Files\*\jdk-*')
    for home in candidates:
        javac = os.path.join(home, 'bin', 'javac.exe' if os.name == 'nt' else 'javac')
        if home and os.path.isfile(javac):
            out = subprocess.run([javac, '-version'], capture_output=True, text=True)
            version = (out.stdout + out.stderr).split()[-1]
            if int(version.split('.')[0]) >= 11:
                return home
    sys.exit('JDK 11+ not found: set JAVA_HOME')


def run(cmd, env=None):
    print('  ' + ' '.join(os.path.basename(c) if i == 0 else c for i, c in enumerate(cmd))[:160])
    result = subprocess.run(cmd, env=env)
    if result.returncode:
        sys.exit('failed (%d)' % result.returncode)


def tool(sdk_tools, name):
    for ext in ('.exe', '.bat', ''):
        p = os.path.join(sdk_tools, name + ext)
        if os.path.isfile(p):
            return p
    sys.exit(name + ' not found in ' + sdk_tools)


def build():
    sdk = find_sdk()
    jdk = find_jdk()
    tools = newest(glob.glob(os.path.join(sdk, 'build-tools', '*')))
    platform = newest([p for p in glob.glob(os.path.join(sdk, 'platforms', 'android-*'))
                       if os.path.isfile(os.path.join(p, 'android.jar'))])
    android_jar = os.path.join(platform, 'android.jar')
    env = dict(os.environ, JAVA_HOME=jdk, PATH=os.path.join(jdk, 'bin') + os.pathsep + os.environ['PATH'])
    print('SDK %s, build-tools %s, %s, JDK %s' % (sdk, os.path.basename(tools), os.path.basename(platform), jdk))

    shutil.rmtree(BUILD, ignore_errors=True)
    classes = os.path.join(BUILD, 'classes')
    dex = os.path.join(BUILD, 'dex')
    os.makedirs(classes)
    os.makedirs(dex)
    unsigned = os.path.join(BUILD, 'unsigned.apk')
    aligned = os.path.join(BUILD, 'aligned.apk')
    apk = os.path.join(BUILD, 'ndrt-video.apk')

    run([tool(tools, 'aapt2'), 'link', '-o', unsigned, '-I', android_jar,
         '--manifest', os.path.join(HERE, 'AndroidManifest.xml'),
         '--min-sdk-version', str(MIN_SDK), '--target-sdk-version', str(TARGET_SDK)])
    sources = glob.glob(os.path.join(HERE, 'src', '**', '*.java'), recursive=True)
    run([os.path.join(jdk, 'bin', 'javac'), '-encoding', 'UTF-8', '-source', '8', '-target', '8',
         '-bootclasspath', android_jar + os.pathsep + os.path.join(tools, 'core-lambda-stubs.jar'), '-Xlint:-options', '-d', classes] + sources, env)
    class_files = glob.glob(os.path.join(classes, '**', '*.class'), recursive=True)
    run([tool(tools, 'd8'), '--release', '--min-api', str(MIN_SDK), '--lib', android_jar,
         '--output', dex] + class_files, env)
    with zipfile.ZipFile(unsigned, 'a', zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(dex, 'classes.dex'), 'classes.dex')
    run([tool(tools, 'zipalign'), '-f', '-p', '4', unsigned, aligned])

    keystore = os.path.expanduser('~/.android/debug.keystore')
    if not os.path.isfile(keystore):
        os.makedirs(os.path.dirname(keystore), exist_ok=True)
        run([os.path.join(jdk, 'bin', 'keytool'), '-genkeypair', '-keystore', keystore, '-storepass', 'android',
             '-alias', 'androiddebugkey', '-keypass', 'android', '-keyalg', 'RSA', '-keysize', '2048',
             '-validity', '10000', '-dname', 'CN=Android Debug,O=Android,C=US'], env)
    run([tool(tools, 'apksigner'), 'sign', '--ks', keystore, '--ks-pass', 'pass:android',
         '--ks-key-alias', 'androiddebugkey', '--key-pass', 'pass:android', '--out', apk, aligned], env)
    print('-> ' + apk)
    return sdk, apk


def adb_path(sdk):
    return os.path.join(sdk, 'platform-tools', 'adb.exe' if os.name == 'nt' else 'adb')


def device_ready(adb):
    out = subprocess.run([adb, 'devices'], capture_output=True, text=True).stdout
    lines = [l.split() for l in out.splitlines()[1:] if l.strip()]
    if not lines:
        sys.exit('no phone on USB: connect it, USB debugging on')
    if not any(len(l) > 1 and l[1] == 'device' for l in lines):
        sys.exit('the phone is %s: allow USB debugging on its screen, then run again' % lines[0][1])


def install(sdk, apk):
    adb = adb_path(sdk)
    device_ready(adb)
    run([adb, 'install', '-r', apk])
    run([adb, 'shell', 'am', 'start', '-n', PACKAGE + '/.MainActivity'])


def push_videos(sdk):
    adb = adb_path(sdk)
    device_ready(adb)
    # the app's folder: made by the app on its first start; made here too in case
    subprocess.run([adb, 'shell', 'mkdir', '-p', PHONE_DIR])
    listing = subprocess.run([adb, 'shell', 'ls', '-l', PHONE_DIR], capture_output=True, text=True,
                             encoding='utf-8', errors='replace').stdout
    paths = sorted(glob.glob(os.path.join(VIDEO_DIR, '*.mp4')))
    if not paths:
        sys.exit('no videos in %s' % VIDEO_DIR)
    # the videos no longer used (not in media/): away, so the app lists only the clips
    names = subprocess.run([adb, 'shell', 'ls', PHONE_DIR], capture_output=True, text=True,
                           encoding='utf-8', errors='replace').stdout.splitlines()
    keep = {os.path.basename(p) for p in paths}
    for name in (n.strip() for n in names):
        if name and name not in keep:
            print('  %s: not in media/, deleted from the phone' % name)
            subprocess.run([adb, 'shell', 'rm', '-f', "'%s/%s'" % (PHONE_DIR, name.replace("'", "'\\''"))])
    for path in paths:
        name = os.path.basename(path)
        size = os.path.getsize(path)
        if any(name in line and str(size) in line.split() for line in listing.splitlines()):
            print('  %s: already on the phone' % name)
            continue
        print('  %s (%.2f GB) -> phone' % (name, size / 2 ** 30))
        run([adb, 'push', path, PHONE_DIR + '/' + name])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--install', action='store_true', help='install on the USB phone and start it')
    parser.add_argument('--videos', action='store_true', help='copy ../*.mp4 into the app folder on the phone')
    parser.add_argument('--videos-only', action='store_true', help='only copy the videos')
    args = parser.parse_args()
    if args.videos_only:
        push_videos(find_sdk())
        return
    sdk, apk = build()
    if args.install:
        install(sdk, apk)
    if args.videos:
        push_videos(sdk)


if __name__ == '__main__':
    main()
