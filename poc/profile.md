## prof0/prof/ai-monitor-1.prof

```text
Wed Nov 18 01:18:35 2026    /tmp/poc171/runs/prof0/prof/ai-monitor-1.prof
         240934363 function calls (239869977 primitive calls) in 61.597 seconds
   Ordered by: cumulative time
   List reduced from 903 to 30 due to restriction <30>
   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
     1169    0.041    0.000  117.475    0.100 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/asyncio/base_events.py:1966(_run_once)
        1    0.000    0.000   61.541   61.541 src/project_index/features/documents/store.py:407(load)
       34    0.006    0.000   58.690    1.726 src/project_index/features/documents/store.py:291(_load_revision_table)
     1027    0.011    0.000   54.954    0.054 src/project_index/features/documents/store.py:321(read)
     1027    0.006    0.000   54.920    0.053 src/project_index/features/documents/loader.py:234(load_file)
     1027    0.005    0.000   53.057    0.052 src/project_index/shared/yaml_io.py:64(load_yaml)
     1027    0.146    0.000   52.921    0.052 .venv/lib/python3.14/site-packages/ruamel/yaml/main.py:438(load)
     1027    0.002    0.000   52.699    0.051 .venv/lib/python3.14/site-packages/ruamel/yaml/constructor.py:115(get_single_data)
     1027    0.008    0.000   52.251    0.051 src/project_index/features/documents/loader.py:131(documents_from_text)
     1027    0.003    0.000   50.607    0.049 .venv/lib/python3.14/site-packages/ruamel/yaml/composer.py:70(get_single_node)
     1027    0.001    0.000   50.493    0.049 .venv/lib/python3.14/site-packages/ruamel/yaml/composer.py:94(compose_document)
518001/1027    1.171    0.000   50.479    0.049 .venv/lib/python3.14/site-packages/ruamel/yaml/composer.py:110(compose_node)
51934/1027    0.404    0.000   50.398    0.049 .venv/lib/python3.14/site-packages/ruamel/yaml/composer.py:203(compose_mapping_node)
17839/3364    0.115    0.000   48.167    0.014 .venv/lib/python3.14/site-packages/ruamel/yaml/composer.py:169(compose_sequence_node)
  1517952    0.642    0.000   41.477    0.000 .venv/lib/python3.14/site-packages/ruamel/yaml/parser.py:137(check_event)
  4451941    2.397    0.000   31.068    0.000 .venv/lib/python3.14/site-packages/ruamel/yaml/scanner.py:167(check_token)
   737885    1.236    0.000   23.853    0.000 .venv/lib/python3.14/site-packages/ruamel/yaml/scanner.py:211(fetch_more_tokens)
   228496    0.542    0.000   19.486    0.000 .venv/lib/python3.14/site-packages/ruamel/yaml/parser.py:627(parse_block_mapping_value)
   280430    0.565    0.000   15.437    0.000 .venv/lib/python3.14/site-packages/ruamel/yaml/parser.py:599(parse_block_mapping_key)
   406204    0.313    0.000   13.043    0.000 .venv/lib/python3.14/site-packages/ruamel/yaml/scanner.py:707(fetch_plain)
   406204    3.744    0.000   11.503    0.000 .venv/lib/python3.14/site-packages/ruamel/yaml/scanner.py:1491(scan_plain)
   518001    1.910    0.000    9.415    0.000 .venv/lib/python3.14/site-packages/ruamel/yaml/parser.py:365(parse_node)
   456992    0.193    0.000    8.215    0.000 .venv/lib/python3.14/site-packages/ruamel/yaml/parser.py:354(parse_block_node_or_indentless_sequence)
        1    0.000    0.000    7.704    7.704 src/project_index/features/documents/store.py:518(_load_walked)
  6951054    3.100    0.000    5.390    0.000 .venv/lib/python3.14/site-packages/ruamel/yaml/scanner.py:196(need_more_tokens)
    61335    0.113    0.000    4.436    0.000 .venv/lib/python3.14/site-packages/ruamel/yaml/parser.py:534(parse_block_sequence_entry)
   237252    0.206    0.000    3.768    0.000 src/project_index/features/sources/types.py:59(matches)
   448166    0.698    0.000    3.480    0.000 .venv/lib/python3.14/site-packages/ruamel/yaml/composer.py:149(compose_scalar_node)
       34    0.064    0.002    3.424    0.101 src/project_index/features/documents/loader.py:24(collect_files)
  2627773    0.895    0.000    3.277    0.000 .venv/lib/python3.14/site-packages/ruamel/yaml/composer.py:44(parser)
```

## prof0/prof/ai-monitor-2.prof

```text
Wed Nov 18 01:18:39 2026    /tmp/poc171/runs/prof0/prof/ai-monitor-2.prof
         15083956 function calls (15070959 primitive calls) in 4.073 seconds
   Ordered by: cumulative time
   List reduced from 204 to 30 due to restriction <30>
   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
      2/1    0.001    0.001    4.073    4.073 src/project_index/features/read/service.py:110(list_documents)
        1    0.001    0.001    4.021    4.021 src/project_index/features/documents/store.py:407(load)
   237252    0.206    0.000    3.760    0.000 src/project_index/features/sources/types.py:59(matches)
       34    0.002    0.000    3.674    0.108 src/project_index/features/documents/store.py:291(_load_revision_table)
       34    0.063    0.002    3.295    0.097 src/project_index/features/documents/loader.py:24(collect_files)
   481411    0.084    0.000    3.245    0.000 src/project_index/features/sources/types.py:62(<genexpr>)
   245135    0.446    0.000    3.172    0.000 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/pathlib/__init__.py:553(full_match)
       75    0.007    0.000    2.207    0.029 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/asyncio/base_events.py:1966(_run_once)
        1    0.000    0.000    2.141    2.141 src/project_index/features/documents/store.py:518(_load_walked)
   490270    0.223    0.000    1.290    0.000 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/pathlib/__init__.py:372(parts)
   978749    0.384    0.000    1.042    0.000 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/pathlib/__init__.py:341(drive)
   500233    0.436    0.000    0.900    0.000 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/pathlib/__init__.py:251(__str__)
   486062    0.294    0.000    0.524    0.000 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/pathlib/__init__.py:281(_parse_path)
   494442    0.274    0.000    0.438    0.000 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/pathlib/__init__.py:135(__init__)
   253384    0.116    0.000    0.401    0.000 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/pathlib/__init__.py:157(with_segments)
   493261    0.173    0.000    0.380    0.000 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/pathlib/__init__.py:261(_format_parsed_parts)
       75    0.002    0.000    0.246    0.003 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/selectors.py:435(select)
       75    0.008    0.000    0.155    0.002 {method 'poll' of 'select.epoll' objects}
   486062    0.096    0.000    0.134    0.000 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/pathlib/__init__.py:330(_raw_path)
   484479    0.087    0.000    0.133    0.000 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/pathlib/__init__.py:125(__new__)
   485012    0.093    0.000    0.130    0.000 <frozen posixpath>:131(splitdrive)
   486062    0.097    0.000    0.097    0.000 {built-in method posix._path_splitroot_ex}
     6979    0.005    0.000    0.097    0.000 src/project_index/features/documents/indexable.py:27(walk_files)
   486062    0.087    0.000    0.087    0.000 {method 'split' of 'str' objects}
  1078435    0.086    0.000    0.086    0.000 {built-in method builtins.isinstance}
   493366    0.077    0.000    0.077    0.000 {method 'join' of 'str' objects}
982895/982889    0.074    0.000    0.074    0.000 {built-in method posix.fspath}
   245135    0.064    0.000    0.064    0.000 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/glob.py:369(compile)
     1750    0.004    0.000    0.063    0.000 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/pathlib/__init__.py:476(relative_to)
   983295    0.058    0.000    0.060    0.000 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/pathlib/__init__.py:359(_tail)
```

## prof3/prof/ai-monitor-1.prof

```text
Wed Nov 18 01:19:32 2026    /tmp/poc171/runs/prof3/prof/ai-monitor-1.prof
         41324157 function calls (40842128 primitive calls) in 14.633 seconds
   Ordered by: cumulative time
   List reduced from 788 to 30 due to restriction <30>
   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
      282    0.048    0.000   16.776    0.059 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/asyncio/base_events.py:1966(_run_once)
      281    0.129    0.000   14.991    0.053 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/selectors.py:435(select)
        1    0.000    0.000   14.591   14.591 src/project_index/features/documents/store.py:407(load)
        1    0.001    0.001   11.982   11.982 src/project_index/features/documents/store.py:518(_load_walked)
       34    0.004    0.000   11.885    0.350 src/project_index/features/documents/store.py:291(_load_revision_table)
     1027    0.007    0.000    7.702    0.007 src/project_index/features/documents/store.py:321(read)
     1027    0.004    0.000    7.639    0.007 src/project_index/features/documents/loader.py:234(load_file)
     1027    0.007    0.000    7.200    0.007 src/project_index/features/documents/loader.py:131(documents_from_text)
     1027    0.003    0.000    5.678    0.006 src/project_index/shared/yaml_io.py:64(load_yaml)
     1027    0.075    0.000    5.241    0.005 .venv/lib/python3.14/site-packages/ruamel/yaml/main.py:438(load)
     1027    0.777    0.001    5.048    0.005 .venv/lib/python3.14/site-packages/ruamel/yaml/constructor.py:115(get_single_data)
   237252    0.223    0.000    4.032    0.000 src/project_index/features/sources/types.py:59(matches)
       34    0.068    0.002    3.600    0.106 src/project_index/features/documents/loader.py:24(collect_files)
   481411    0.091    0.000    3.482    0.000 src/project_index/features/sources/types.py:62(<genexpr>)
   245135    0.483    0.000    3.402    0.000 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/pathlib/__init__.py:553(full_match)
        1    0.009    0.009    2.318    2.318 src/project_index/features/documents/store.py:174(_revision_root)
        1    0.000    0.000    2.308    2.308 src/project_index/features/history/snapshot.py:87(checkout)
     1027    0.022    0.000    2.216    0.002 .venv/lib/python3.14/site-packages/ruamel/yaml/constructor.py:122(construct_document)
103868/97954    0.031    0.000    2.042    0.000 .venv/lib/python3.14/site-packages/ruamel/yaml/constructor.py:626(construct_yaml_map)
    51934    0.038    0.000    2.000    0.000 .venv/lib/python3.14/site-packages/ruamel/yaml/constructor.py:419(construct_mapping)
   518402    0.423    0.000    1.892    0.000 .venv/lib/python3.14/site-packages/ruamel/yaml/resolver.py:352(resolve)
        1    0.017    0.017    1.645    1.645 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/tarfile.py:2388(extractall)
    51934    0.231    0.000    1.628    0.000 .venv/lib/python3.14/site-packages/ruamel/yaml/constructor.py:217(construct_mapping)
   490270    0.239    0.000    1.378    0.000 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/pathlib/__init__.py:372(parts)
       11    0.016    0.001    1.315    0.120 src/project_index/features/documents/loader.py:177(_record_documents)
   812808    0.440    0.000    1.269    0.000 .venv/lib/python3.14/site-packages/ruamel/yaml/resolver.py:338(versioned_resolver)
   518001    0.215    0.000    1.255    0.000 .venv/lib/python3.14/site-packages/ruamel/yaml/constructor.py:135(construct_object)
   996096    0.426    0.000    1.190    0.000 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/pathlib/__init__.py:341(drive)
   572148    0.490    0.000    1.072    0.000 /home/shuhei2441/.local/share/uv/python/cpython-3.14.3-linux-x86_64-gnu/lib/python3.14/pathlib/__init__.py:251(__str__)
   517939    0.294    0.000    1.040    0.000 .venv/lib/python3.14/site-packages/ruamel/yaml/constructor.py:158(construct_non_recursive_object)
```

