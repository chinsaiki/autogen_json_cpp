# -*- coding: <encoding name> -*- : # -*- coding: utf-8 -*-
import json
import sys
import os

from autogen_json_type import cpp_headers, keep_words

json_cpp_headers = \
"""
#include "types/s4type.h"
#include "db_sqlite/tableIO.h"
#include <SQLiteCpp/ExecuteMany.h>

#include "jsonTypes/{}.h"
"""

namespace_head = \
"""
namespace S4 {
namespace sqlite {
"""

namespace_tail = \
"""
}//namespace sqlite
}//namespace S4
"""


def determin_value_type_sqlite(value):
    if isinstance(value, str):
        return "TEXT"
    elif isinstance(value, bool):
        return " BOOLEAN"
    elif isinstance(value, int):
        return "INTEGER"
    elif isinstance(value, float):
        return "DOUBLE"

def get_func(value):
    if value == "TEXT":
        return "getString"
    elif value == "BOOLEAN":
        return "getInt64"
    elif value == "INTEGER":
        return "getInt64"
    elif value == "DOUBLE":
        return "getDouble"

def get_type(value):
    if value == "TEXT":
        return "std::string"
    elif value == "BOOLEAN":
        return "bool"
    elif value == "INTEGER":
        return "int"
    elif value == "DOUBLE":
        return "double"

# not support list or dict within dict
# cols[key_name] = key_type
def dict_to_cols(json_dict):
    cols = {}

    if '__assign_type_fields__' in json_dict:
        __assign_type_fields__ = json_dict['__assign_type_fields__']
        print("use __assign_type_fields__ = {}".format(__assign_type_fields__))
    else:
        __assign_type_fields__ = {}
        
    if '__assign_enum_fields__' in json_dict:
        __assign_enum_fields__ = json_dict['__assign_enum_fields__']
        print("use __assign_enum_fields__ = {}".format(__assign_enum_fields__))
    else:
        __assign_enum_fields__ = {}

    for key_name in json_dict:
        if key_name in keep_words or key_name.find("__comment__")==0:
            continue

        key_value = json_dict[key_name]

        if key_name in __assign_enum_fields__:
            cols[key_name] = "TEXT"
        elif isinstance(key_value, (str, int, float, bool)):
            key_type = determin_value_type_sqlite(key_value)
            cols[key_name] = key_type
        elif isinstance(key_value, dict):
            print("unsupported type for <dict> {}:{}".format(key_name, key_value))
            exit(-1)
        elif isinstance(key_value, list):
            print("unsupported type for <list> {}:{}".format(key_name, key_value))
            exit(-1)
            # if len(key_value)==0:
            # else:
            #     key_value = key_value[0]
            #     if isinstance(key_value, (str, int, float, bool) or key_name in __assign_type_fields__):
            #     elif isinstance(key_value, dict):
            #     else:
            #         print("unsupported list type for {}:{}".format(key_name, key_value))
            #         exit(-1)
        else:
            print("unsupported type for {}:{}".format(key_name, key_value))
            exit(-1)

    return cols, __assign_type_fields__, __assign_enum_fields__


PRIMARY_KEY_in_order = [ 'id', 'date', 'mktCode', 'datetime', 'code']

# cols[key_name] = key_type
def get_K_COL(cols, primary = None):
    K_COL = \
"""
const std::string K_COL =
    "( "
"""
    primary_key = primary
    for name in cols:
        v_type = cols[name]
        K_COL += '        "{}\t{}, "\n'.format(name, v_type)

    if primary_key is None:
        for key in PRIMARY_KEY_in_order:
            if key in cols:
                primary_key = key
                break

    K_COL += \
'''
        "PRIMARY KEY({})"
    ")";
'''.format(primary_key)

    return K_COL

def get_K_IN(cols):
    
    K_IN = \
'''
const std::string K_IN =
    "("'''
    l = []
    for name in cols:
        l.append(name)

    K_IN += \
"""
    "{}"
    ") VALUES ({})"
;
""".format(", ".join(l), ','.join(['?']*len(cols)))

    return K_IN

def get_bind(col_list, __assign_enum_fields__):
    n = 1
    ret = []
    for col in cols:
        if col in __assign_enum_fields__:
            as_type = __assign_enum_fields__[col]
            ret.append('query.bind({}, {}_toString(K_data.{}));'.format(n, as_type, col))
        else:
            ret.append('query.bind({}, K_data.{});'.format(n, col))
        n += 1


    return '\r\n\t\t'.join(ret)


def get_load_code(cols, __assign_type_fields__, __assign_enum_fields__):
    n=0
    load = []
    load_single = []
    for col in cols:
        if col in __assign_enum_fields__:
            as_type = __assign_enum_fields__[col]
            l = "K_data.{} = {}_fromString(query.getColumn({}).{}());".format(col, as_type, n, get_func(cols[col]))
            ls = '''
    static inline
    {1} load_query_{0}(SQLite::Statement& query)
    {{
        return {1}_fromString(query.getColumn({2}).{3}());
    }}
            '''.format(col, as_type, n, get_func(cols[col]))
        else:
            if col in __assign_type_fields__:
                as_type = '{}'.format(__assign_type_fields__[col])
            else:
                as_type = '{}'.format(get_type(cols[col]))
            l = "K_data.{} = ({})query.getColumn({}).{}();".format(col, as_type, n, get_func(cols[col]))
            ls = '''
    static inline
    {0} load_query_{1}(SQLite::Statement& query)
    {{
        return ({0})query.getColumn({2}).{3}();
    }}
            '''.format(as_type, col, n, get_func(cols[col]))
        n += 1
        load.append(l)
        load_single.append(ls)

    load = "\n\t\t".join(load)
    load_single = "\n\t\t".join(load_single)
    return load, load_single



def get_class(data_type_name, io_class_name, K_COL, K_IN, cols, __assign_type_fields__, __assign_enum_fields__, __sqlite_read_only__):
    n = 0
    col_list = []
    for col in cols:
        col_list.append(col)

    load, load_single = get_load_code(cols, __assign_type_fields__, __assign_enum_fields__)

    bindStr = get_bind(col_list, __assign_enum_fields__)

    if __sqlite_read_only__:
        qurey_build = '""'
        K_COL = 'const std::string K_COL = "";'
        qurey_bind = '''
    static
    void bind_query(SQLite::Statement& , const std::vector<struct {0}>& , size_t )
    {{
    }}'''.format(data_type_name)
    else:
        qurey_build = '"CREATE TABLE if not exists " + m_name + K_COL'
        qurey_bind = '''
    static
    void bind_query(SQLite::Statement& query, const std::vector<struct {0}>& data, size_t nb)
    {{
        const struct {0} & K_data = data[nb];
        {1}
    }}'''.format(data_type_name, bindStr)

    class_str = \
"""
class {1} : public tableIO_t<struct {0}>{{
public:
    typedef struct {0} data_t;
	//{1}(const std::string name)
    //{{
    //    set_name(name);
    //}};
    
	virtual void set_name(const std::string& name) override {{
        m_name = name;
        m_qurey_build = {6};
        m_qurey_insert = "INSERT OR IGNORE INTO " + m_name + K_IN;
    }}

    virtual const std::string & get_query_build(void) const override {{ return m_qurey_build;}};

    virtual const std::string & get_query_insert(void) const override {{ return m_qurey_insert;}};
    
{4}

    //warning: not clear data inside, but append DB.data to it
    static
    void load_query(SQLite::Statement& query, std::vector<{0}>& data)
    {{
        struct {0} K_data;
        {5}
        data.push_back(std::move(K_data));
    }}

    {7}
private:
	//std::string m_name;
    std::string m_qurey_build;
    std::string m_qurey_insert;
private:
{2}

{3}

}};
""".format(data_type_name, io_class_name, K_COL, K_IN, qurey_bind, load, qurey_build, load_single)
    return class_str


if __name__ == "__main__":
    print("Current working path={}".format(os.getcwd()))

    if len(sys.argv)==1:
        print("Need at least 1 arg:")
        print("  {} <json file>  [<output file>]".format(sys.argv[0]))
        exit(1)

    src_json = sys.argv[1]
    print("reading json file:{}".format(src_json))
    with open(src_json, 'r', encoding='UTF-8') as f:
        text = f.readlines()
    # print(text)
    text = "".join(text)
    json_instance = json.loads(text)

    # print("read json OK:\n{}".format(json.dumps(json_instance, indent=4, separators=(',', ': '))))

    print("read json base type={}".format(type(json_instance)))
    if not isinstance(json_instance, dict):
        print("error:only support base type==dict for now!")
        exit(0)

    if "__sqlite_capable__" not in json_instance:
        print("not __sqlite_capable__")
        exit(0)

    primary = None
    if "__sqlite_primary__" in json_instance:
        primary = json_instance["__sqlite_primary__"]
    
    if "__sqlite_read_only__" in json_instance:
        __sqlite_read_only__ = json_instance["__sqlite_read_only__"]
    else:
        __sqlite_read_only__ = False

    data_type_name = os.path.basename(src_json)
    data_type_name = data_type_name.split(".")[0]
    if __sqlite_read_only__:
        io_class_name = data_type_name + "_dbTbl_ro"
    else:
        io_class_name = data_type_name + "_dbTbl"
    print("Creating Cpp file for type={}, tbl_class={}".format(data_type_name, io_class_name))

    if len(sys.argv)>=3:
        tgt_cpp = sys.argv[2]
        if os.path.isdir(tgt_cpp):
            tgt_cpp = tgt_cpp + "/" + io_class_name + ".h"
    else:
        if __sqlite_read_only__:
            tgt_cpp = src_json.replace(".json", "_dbTbl_ro.h")
        else:
            tgt_cpp = src_json.replace(".json", "_dbTbl.h")


    cols, __assign_type_fields__, __assign_enum_fields__ = dict_to_cols(json_instance)
    K_IN = get_K_IN(cols)
    K_COL = get_K_COL(cols, primary)
    class_t = get_class(data_type_name, io_class_name, K_COL, K_IN, cols, __assign_type_fields__, __assign_enum_fields__, __sqlite_read_only__)
    # print(class_t)

#     data_vec = ''' 
# class {0}_vector : public std::vector<{0}>
# {{
# public:
#     typedef {0}_dbTbl tableIO_t;
# }};
#     '''.format(data_type_name)

    output_text = cpp_headers + json_cpp_headers.format(data_type_name) + namespace_head + class_t + namespace_tail
    
    if tgt_cpp is not None:
        with open(tgt_cpp, 'w+') as fo:
            fo.write(output_text)

