#!/usr/bin/env bash

# Calculate the maximum CPU threads
max_threads=$(nproc --all)

# Update the XML content with the calculated max_threads value
updated_xml=$(cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policymap [
<!ELEMENT policymap (policy)*>
<!ATTLIST policymap xmlns CDATA #FIXED "">
<!ELEMENT policy EMPTY>
<!ATTLIST policy xmlns CDATA #FIXED "">
<!ATTLIST policy domain NMTOKEN #REQUIRED>
<!ATTLIST policy name NMTOKEN #IMPLIED>
<!ATTLIST policy pattern CDATA #IMPLIED>
<!ATTLIST policy rights NMTOKEN #IMPLIED>
<!ATTLIST policy stealth NMTOKEN #IMPLIED>
<!ATTLIST policy value CDATA #IMPLIED>
]>
<policymap>
  <policy domain="Undefined" rights="none"/>
  <!-- Set maximum parallel threads. -->
       <policy domain="resource" name="thread" value="$max_threads"/>
  <!-- Set maximum time to live in seconds or neumonics, e.g. "2 minutes". When
       this limit is exceeded, an exception is thrown and processing stops. -->
  <!-- <policy domain="resource" name="time" value="120"/> -->
  <!-- Set maximum number of open pixel cache files. When this limit is
       exceeded, any subsequent pixels cached to disk are closed and reopened
       on demand. -->
       <policy domain="resource" name="file" value="999999"/>
  <!-- Set maximum amount of memory in bytes to allocate for the pixel cache
       from the heap. When this limit is exceeded, the image pixels are cached
       to memory-mapped disk. -->
       <policy domain="resource" name="memory" value="16GiB"/>
  <!-- Set maximum amount of memory map in bytes to allocate for the pixel
       cache. When this limit is exceeded, the image pixels are cached to
       disk. -->
       <policy domain="resource" name="map" value="16GiB"/>
  <!-- Set the maximum width * height of an image that can reside in the pixel
       cache memory. Images that exceed the area limit are cached to disk. -->
       <policy domain="resource" name="area" value="32GP"/>
  <!-- Set maximum amount of disk space in bytes permitted for use by the pixel
       cache. When this limit is exceeded, the pixel cache is not be created
       and an exception is thrown. -->
       <policy domain="resource" name="disk" value="16GiB"/>
  <!-- Set the maximum length of an image sequence.  When this limit is
       exceeded, an exception is thrown. -->
       <policy domain="resource" name="list-length" value="128KP"/>
  <!-- Set the maximum width of an image.  When this limit is exceeded, an
       exception is thrown. -->
       <policy domain="resource" name="width" value="64KP"/>
  <!-- Set the maximum height of an image.  When this limit is exceeded, an
       exception is thrown. -->
       <policy domain="resource" name="height" value="64KP"/>
  <!-- Periodically yield the CPU for at least the time specified in
       milliseconds. -->
  <!-- <policy domain="resource" name="throttle" value="2"/> -->
  <!-- Do not create temporary files in the default shared directories, instead
       specify a private area to store only ImageMagick temporary files. -->
  <!-- <policy domain="resource" name="temporary-path" value="/magick/tmp/"/> -->
  <!-- Force memory initialization by memory mapping select memory
       allocations. -->
  <!-- <policy domain="cache" name="memory-map" value="anonymous"/> -->
  <!-- Ensure all image data is fully flushed and synchronized to disk. -->
  <!-- <policy domain="cache" name="synchronize" value="true"/> -->
  <!-- Replace passphrase for secure distributed processing -->
  <!-- <policy domain="cache" name="shared-secret" value="secret-passphrase" stealth="true"/> -->
  <!-- Do not permit any delegates to execute. -->
  <!-- <policy domain="delegate" rights="none" pattern="*"/> -->
  <!-- Do not permit any image filters to load. -->
  <!-- <policy domain="filter" rights="none" pattern="*"/> -->
  <!-- Don't read/write from/to stdin/stdout. -->
  <!-- <policy domain="path" rights="none" pattern="-"/> -->
  <!-- don't read sensitive paths. -->
  <!-- <policy domain="path" rights="none" pattern="/etc/*"/> -->
  <!-- Indirect reads are not permitted. -->
  <!-- <policy domain="path" rights="none" pattern="@*"/> -->
  <!-- These image types are security risks on read, but write is fine -->
  <!-- <policy domain="module" rights="write" pattern="{MSL,MVG,PS,SVG,URL,XPS}"/> -->
  <!-- This policy sets the number of times to replace content of certain
       memory buffers and temporary files before they are freed or deleted. -->
  <!-- <policy domain="system" name="shred" value="1"/> -->
  <!-- Enable the initialization of buffers with zeros, resulting in a minor
       performance penalty but with improved security. -->
  <!-- <policy domain="system" name="memory-map" value="anonymous"/> -->
  <!-- Set the maximum amount of memory in bytes that are permitted for
       allocation requests. -->
  <!-- <policy domain="system" name="max-memory-request" value="256MiB"/> -->
</policymap>
EOF
)

# Save the updated XML content to the specified file
echo "$updated_xml" | sudo tee "/usr/local/etc/ImageMagick-7/policy.xml" >/dev/null
