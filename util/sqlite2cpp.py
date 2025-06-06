#!/usr/bin/env python
# vi:tabstop=4:expandtab:shiftwidth=4:softtabstop=4:autoindent:smarttab
'''
Usage: python sqlite2cpp.py path_to_sql_file
'''

import sys
import os
import datetime
import sqlite3
import codecs

currency_unicode_patch_filename = 'currencies_update_patch_unicode_only.mmdbg'
currency_table_patch_filename = 'currencies_update_patch.mmdbg'
sql_tables_data_filename = 'sql_tables.sql'

# http://stackoverflow.com/questions/196345/how-to-check-if-a-string-in-python-is-in-ascii
def is_ascii(s):
    """Class: Check for Ascii String"""
    if isinstance(s, str):
        return all(ord(c) < 128 for c in s)
    return False

def is_trans(s):
    """Check translation requirements for cpp"""
    if isinstance(s, int):
        return False

    if not is_ascii(s): # it is unicode string
        return True

    if len(s) > 4 and s[0:4] == "_tr_": # requires wxTRANSLATE for cpp
        return True

    return False

def adjust_translate(s):
    """Return the correct translated syntax for c++"""
    trans_str = s.replace("_tr_", "").replace('"','')
    trans_str = '_("' + trans_str + '")'

    return trans_str

def translation_for(s):
    """Return the correct translated syntax for c++"""
    trans_str = ''
    if not is_ascii(s):  # it is unicode string
        if len(s) > 4 and s[0:4] == "_tr_": # requires wxTRANSLATE for cpp
            trans_str = adjust_translate(s)
        else:
            trans_str = 'L"%s"' % s
    else:
        trans_str = adjust_translate(s)

    return trans_str

# https://github.com/django/django/blob/master/django/db/backends/sqlite3/introspection.py
def get_table_list(cursor):
    "Returns a list of table names in the current database."
    # Skip the sqlite_sequence system table used for autoincrement key
    # generation.
    cursor.execute("""
        SELECT name, sql FROM sqlite_master
        WHERE type='table' AND NOT name='sqlite_sequence'
        ORDER BY name""")
    return [(row[0], row[1]) for row in cursor.fetchall()]


def get_table_info(cursor, name):
    cursor.execute('PRAGMA table_info(%s)' % name)
    # cid, name, type, notnull, dflt_value, pk
    return [{'cid': field[0],
             'name': field[1],
             'type': field[2].upper(),
             'null_ok': not field[3],
             'pk': field[5]     # undocumented
            } for field in cursor.fetchall()]

def get_index_list(cursor, tbl_name):
    "Returns a list of table names in the current database."
    # Skip the sqlite_sequence system table used for autoincrement key
    # generation.
    cursor.execute("""
        SELECT tbl_name, sql FROM sqlite_master
        WHERE type='index' AND name NOT LIKE 'sqlite_autoindex_%%' AND tbl_name = '%s'
        ORDER BY name""" % tbl_name)
    return [row[1] for row in cursor.fetchall()]

def get_data_initializer_list(cursor, tbl_name):
    "Returns a list of data in the current table."
    cursor.execute("select * from %s" % tbl_name)
    return cursor.fetchall()

base_data_types_reverse = {
    'TEXT': 'wxString',
    'NUMERIC': 'double',
    'INTEGER': 'int64',
    'REAL': 'double',
    'BLOB': 'wxString',
    'DATE': 'wxDateTime',
}

base_data_types_function = {
    'TEXT': 'GetString',
    'NUMERIC': 'GetDouble',
    'INTEGER': 'GetInt64',
    'REAL': 'GetDouble',
}

class DB_Table:
    """ Class: Defines the database table in SQLite3"""
    def __init__(self, table, fields, index, data):
        self._table = table
        self._fields = fields
        self._primay_key = [field['name'] for field in self._fields if field['pk']][0]
        self._index = index
        self._data = data

    def generate_currency_table_data(self, sf1, utf_only):
        """Extract currency table data from table_v1
           Return string of update commands
           Will only get unicode data line when utf_only is true"""

        for row in self._data:
            values = ', '.join(["%s='%s'" % (k, row[k]) for k in row.keys() if k.upper() != 'CURRENCYID' and k.upper() != 'CURRENCY_SYMBOL'])
            values = values.replace('_tr_', '')

            if not utf_only or not is_ascii(values):
                sf1 += '''
INSERT OR IGNORE INTO %s (CURRENCYNAME, CURRENCY_SYMBOL) VALUES ('%s', '%s');
UPDATE OR IGNORE %s SET %s WHERE CURRENCY_SYMBOL='%s';''' % (self._table, row['CURRENCYNAME'].replace('_tr_', ''), row['CURRENCY_SYMBOL'], self._table, values, row['CURRENCY_SYMBOL'])

        return sf1

    def generate_unicode_currency_upgrade_patch(self):
        """Write database_version data to file
           Only extract unicode data"""
        if self._table.upper() == 'CURRENCYFORMATS_V1':
            print ('Generate patch file: %s' % currency_unicode_patch_filename)
            rfp = codecs.open(currency_unicode_patch_filename, 'w', 'utf-8')
            sf1 = '''-- MMEX Debug SQL - Update --
-- MMEX db version required 10
-- This script will add missing currencies and will overwrite all currencies params containing UTF8 in your database.'''
            rfp.write(self.generate_currency_table_data(sf1, True))
            rfp.close()

    def generate_currency_upgrade_patch(self):
        """Write currency_table_upgrade_patch file
           Extract all currency data"""
        if self._table.upper() == 'CURRENCYFORMATS_V1':
            print ('Generate patch file: %s' % currency_table_patch_filename)
            rfp = codecs.open(currency_table_patch_filename, 'w', 'utf-8')
            sf1 = '''-- MMEX Debug SQL - Update --
-- MMEX db version required 10
-- This script will add missing currencies and will overwrite all currencies params in your database.'''
            rfp.write(self.generate_currency_table_data(sf1, False))
            rfp.close()

    def generate_class(self, header, sql):
        """ Write the data to the appropriate .h file"""
        print ('Generate Table: %s' % self._table)
        rfp = codecs.open('DB_Table_' + self._table.title() + '.h', 'w', 'utf-8-sig')
        rfp.write(header + self.to_string(sql))
        rfp.close()

    def to_string(self, sql=None):
        """Create the data for the .h file"""
        s = '''#pragma once

#include "DB_Table.h"

struct DB_Table_%s : public DB_Table
{
    struct Data;
    typedef DB_Table_%s Self;

    /** A container to hold list of Data records for the table*/
    struct Data_Set : public std::vector<Self::Data>
    {
        /**Return the data records as a json array string */
        wxString to_json() const
        {
            StringBuffer json_buffer;
            PrettyWriter<StringBuffer> json_writer(json_buffer);

            json_writer.StartArray();
            for (const auto & item: *this)
            {
                json_writer.StartObject();
                item.as_json(json_writer);
                json_writer.EndObject();
            }
            json_writer.EndArray();

            return json_buffer.GetString();
        }
    };

    /** A container to hold a list of Data record pointers for the table in memory*/
    typedef std::vector<Self::Data*> Cache;
    typedef std::map<int64, Self::Data*> Index_By_Id;
    Cache cache_;
    Index_By_Id index_by_id_;
    Data* fake_; // in case the entity not found

    /** Destructor: clears any data records stored in memory */
    ~DB_Table_%s() 
    {
        delete this->fake_;
        destroy_cache();
    }
     
    /** Removes all records stored in memory (cache) for the table*/ 
    void destroy_cache()
    {
        std::for_each(cache_.begin(), cache_.end(), std::mem_fn(&Data::destroy));
        cache_.clear();
        index_by_id_.clear(); // no memory release since it just stores pointer and the according objects are in cache
    }
''' % (self._table, self._table, self._table)

        s += '''
    /** Creates the database table if the table does not exist*/
    bool ensure(wxSQLite3Database* db)
    {
        if (!exists(db))
        {
            try
            {
                db->ExecuteUpdate("%s");
                this->ensure_data(db);
            }
            catch(const wxSQLite3Exception &e) 
            { 
                wxLogError("%s: Exception %%s", e.GetMessage().utf8_str());
                return false;
            }
        }

        this->ensure_index(db);

        return true;
    }
''' % (sql.replace('\n', ''), self._table)

        s += '''
    bool ensure_index(wxSQLite3Database* db)
    {
        try
        {'''
        for i in self._index:
            mi = i.split()
            mi.insert(2, 'IF')
            mi.insert(3, 'NOT')
            mi.insert(4, 'EXISTS')
            ni = ' '.join(mi)
            s += '''
            db->ExecuteUpdate("%s");''' % (ni.replace('\n', ''))

        s += '''
        }
        catch(const wxSQLite3Exception &e) 
        { 
            wxLogError("%s: Exception %%s", e.GetMessage().utf8_str());
            return false;
        }

        return true;
    }
''' % (self._table)

        s += '''
    void ensure_data(wxSQLite3Database* db)
    {
        db->Begin();'''

        rf1, rf2, rf3 = '', '', ''
        for r in self._data:
            rf2 = ', '.join(["'%s'" if is_trans(i) else "'%s'" % i for i in r])
            rf3 = ', '.join([translation_for(i) for i in r if is_trans(i)])
            if rf2.find('%s') >= 0:
                rf3 = ', ' + rf3
            rf1 = '"INSERT INTO %s VALUES (%s)"%s' % (self._table, rf2, rf3)
            if rf2.find('%s') >= 0:
                rf1 = 'wxString::Format(' + rf1 + ')'
            s += '''
        db->ExecuteUpdate(%s);''' % (rf1)

        s += '''
        db->Commit();
    }
    '''

        for field in self._fields:
            s += '''
    struct %s : public DB_Column<%s>
    { 
        static wxString name() { return "%s"; } 
        explicit %s(const %s &v, OP op = EQUAL): DB_Column<%s>(v, op) {}
    };
    ''' % (field['name'], base_data_types_reverse[field['type']], field['name'],
             field['name'], base_data_types_reverse[field['type']],
             base_data_types_reverse[field['type']])

        s += '''
    typedef %s PRIMARY;''' % self._primay_key

        s += '''
    enum COLUMN
    {
        COL_%s = 0''' % self._primay_key.upper()

        for index, name in enumerate([field['name'] for field in self._fields if not field['pk']]):
            s += '''
        , COL_%s = %d''' % (name.upper(), index +1)

        s += '''
    };
'''
        s += '''
    /** Returns the column name as a string*/
    static wxString column_to_name(const COLUMN col)
    {
        switch(col)
        {
            case COL_%s: return "%s";''' % (self._primay_key.upper(), self._primay_key)

        for index, name in enumerate([field['name'] for field in self._fields if not field['pk']]):
            s += '''
            case COL_%s: return "%s";''' %(name.upper(), name)
        s += '''
            default: break;
        }
        
        return "UNKNOWN";
    }
'''
        s += '''
    /** Returns the column number from the given column name*/
    static COLUMN name_to_column(const wxString& name)
    {
        if ("%s" == name) return COL_%s;''' % (self._primay_key, self._primay_key.upper())

        for index, name in enumerate([field['name'] for field in self._fields if not field['pk']]):
            s += '''
        else if ("%s" == name) return COL_%s;''' %(name, name.upper())

        s += '''

        return COLUMN(-1);
    }
    '''
        s += '''
    /** Data is a single record in the database table*/
    struct Data
    {
        friend struct DB_Table_%s;
        /** This is a instance pointer to itself in memory. */
        Self* table_;
    ''' % self._table.upper()
        for field in self._fields:
            s += '''
        %s %s;%s''' % (
            base_data_types_reverse[field['type']],
            field['name'], field['pk'] and '//  primary key' or '')

        s += '''

        int64 id() const
        {
            return %s;
        }

        void id(const int64 id)
        {
            %s = id;
        }

        auto operator < (const Data& other) const
        {
            return this->id() < other.id();
        }

        auto operator < (const Data* other) const
        {
            return this->id() < other->id();
        }
''' % (self._primay_key, self._primay_key)

        s += '''
        bool equals(const Data* r) const
        {'''
        for field in self._fields:
            ftype = base_data_types_reverse[field['type']]
            if ftype == 'int64' or ftype == 'double':
                s += '''
            if(%s != r->%s) return false;''' % (field['name'], field['name'])
            elif ftype == 'wxString':
                s += '''
            if(!%s.IsSameAs(r->%s)) return false;''' % (field['name'], field['name'])
        s += '''
            return true;
        }
        
        explicit Data(Self* table = nullptr ) 
        {
            table_ = table;
        '''

        for field in self._fields:
            ftype = base_data_types_reverse[field['type']]
            if ftype == 'wxString':
                continue
            elif ftype == 'double':
                s += '''
            %s = 0.0;''' % field['name']
            elif ftype == 'int64':
                s += '''
            %s = -1;''' % field['name']


        s += '''
        }

        explicit Data(wxSQLite3ResultSet& q, Self* table = nullptr )
        {
            table_ = table;
        '''
        for field in self._fields:
            func = base_data_types_function[field['type']]
            s += '''
            %s = q.%s(%d); // %s''' % (field['name'], func, field['cid'], field['name'])

        s += '''
        }

        Data(const Data& other) = default;

        Data& operator=(const Data& other)
        {
            if (this == &other) return *this;
'''
        for field in self._fields:
            s += '''
            %s = other.%s;''' % (field['name'], field['name'])
        s += '''
            return *this;
        }
'''
        s += '''
        template<typename C>
        bool match(const C &) const
        {
            return false;
        }'''
        for field in self._fields:
            ftype = base_data_types_reverse[field['type']]
            if ftype == 'wxString':
                s += '''

        bool match(const Self::%s &in) const
        {
            return this->%s.CmpNoCase(in.v_) == 0;
        }''' % (field['name'], field['name'])
            else:
                s += '''

        bool match(const Self::%s &in) const
        {
            return this->%s == in.v_;
        }''' % (field['name'], field['name'])

        s += '''

        // Return the data record as a json string
        wxString to_json() const
        {
            StringBuffer json_buffer;
            PrettyWriter<StringBuffer> json_writer(json_buffer);

			json_writer.StartObject();			
			this->as_json(json_writer);
            json_writer.EndObject();

            return json_buffer.GetString();
        }

        // Add the field data as json key:value pairs
        void as_json(PrettyWriter<StringBuffer>& json_writer) const
        {'''
        for field in self._fields:
            type = base_data_types_reverse[field['type']]
            if type == 'int64':
                s += '''
            json_writer.Key("%s");
            json_writer.Int64(this->%s.GetValue());''' % (field['name'], field['name'])
            elif type == 'double':
                s += '''
            json_writer.Key("%s");
            json_writer.Double(this->%s);''' % (field['name'], field['name'])
            elif type == 'wxString':
                s += '''
            json_writer.Key("%s");
            json_writer.String(this->%s.utf8_str());''' % (field['name'], field['name'])
            else:
                assert "Field type Error"

        s += '''
        }'''

        s += '''

        row_t to_row_t() const
        {
            row_t row;'''
        for field in self._fields:
            s += '''
            row(L"%s") = %s;'''%(field['name'], field['name'] + '.GetValue()' if field['type'] == 'INTEGER' else field['name'])

        s += '''
            return row;
        }'''

        s += '''

        void to_template(html_template& t) const
        {'''
        for field in self._fields:
            s += '''
            t(L"%s") = %s;''' % (field['name'], field['name'] + '.GetValue()' if field['type'] == 'INTEGER' else field['name'])

        s += '''
        }'''

        s += '''

        /** Save the record instance in memory to the database. */
        bool save(wxSQLite3Database* db, bool force_insert = false)
        {
            if (db && db->IsReadOnly()) return false;
            if (!table_ || !db) 
            {
                wxLogError("can not save %s");
                return false;
            }

            return table_->save(this, db, force_insert);
        }

        /** Remove the record instance from memory and the database. */
        bool remove(wxSQLite3Database* db)
        {
            if (!table_ || !db) 
            {
                wxLogError("can not remove %s");
                return false;
            }
            
            return table_->remove(this, db);
        }

        void destroy()
        {
            delete this;
        }
    };
''' % (self._table.upper(), self._table.upper())
        s += '''
    enum
    {
        NUM_COLUMNS = %d
    };

    size_t num_columns() const { return NUM_COLUMNS; }
''' % len(self._fields)

        s += '''
    /** Name of the table*/    
    wxString name() const { return "%s"; }
''' % self._table

        s += '''
    DB_Table_%s() : fake_(new Data())
    {
        query_ = "SELECT %s FROM %s ";
    }
''' % (self._table, ', '.join([field['name'] for field in self._fields]), self._table)

        s += '''
    /** Create a new Data record and add to memory table (cache)*/
    Self::Data* create()
    {
        Self::Data* entity = new Self::Data(this);
        cache_.push_back(entity);
        return entity;
    }
    
    /** Create a copy of the Data record and add to memory table (cache)*/
    Self::Data* clone(const Data* e)
    {
        Self::Data* entity = create();
        *entity = *e;
        entity->id(-1);
        return entity;
    }
'''
        s += '''
    /**
    * Saves the Data record to the database table.
    * Either create a new record or update the existing record.
    * Remove old record from the memory table (cache)
    */
    bool save(Self::Data* entity, wxSQLite3Database* db, bool force_insert = false)
    {
        wxString sql = wxEmptyString;
        if (entity->id() <= 0 || force_insert) //  new & insert
        {
            sql = "INSERT INTO %s(%s, %s) VALUES(%s)";
        }''' % (self._table, ', '.join([field['name']\
                for field in self._fields if not field['pk']]), self._primay_key,
                ', '.join(['?' for field in self._fields]))

        s += '''
        else
        {
            sql = "UPDATE %s SET %s WHERE %s = ?";
        }

        try
        {
            wxSQLite3Statement stmt = db->PrepareStatement(sql);
''' % (self._table, ', '.join([field['name'] + ' = ?'\
        for field in self._fields if not field['pk']]), self._primay_key)

        for index, name in enumerate([field['name'] for field in self._fields if not field['pk']]):
            s += '''
            stmt.Bind(%d, entity->%s);'''% (index + 1, name)


        s += '''
            stmt.Bind(%d, entity->id() > 0 ? entity->%s : newId());

            stmt.ExecuteUpdate();
            stmt.Finalize();

            if (entity->id() > 0) // existent
            {
                for(Cache::iterator it = cache_.begin(); it != cache_.end(); ++ it)
                {
                    Self::Data* e = *it;
                    if (e->id() == entity->id()) 
                        *e = *entity;  // in-place update
                }
            }
        }
        catch(const wxSQLite3Exception &e) 
        { 
            wxLogError("%s: Exception %%s, %%s", e.GetMessage().utf8_str(), entity->to_json());
            return false;
        }

        if (entity->id() <= 0)
        {
            entity->id(db->GetLastRowId());
            index_by_id_.insert(std::make_pair(entity->id(), entity));
        }
        return true;
    }
''' % (len(self._fields), self._primay_key, self._table)

        s += '''
    /** Remove the Data record from the database and the memory table (cache) */
    bool remove(const int64 id, wxSQLite3Database* db)
    {
        if (id <= 0) return false;
        try
        {
            wxString sql = "DELETE FROM %s WHERE %s = ?";
            wxSQLite3Statement stmt = db->PrepareStatement(sql);
            stmt.Bind(1, id);
            stmt.ExecuteUpdate();
            stmt.Finalize();

            Cache c;
            for(Cache::iterator it = cache_.begin(); it != cache_.end(); ++ it)
            {
                Self::Data* entity = *it;
                if (entity->id() == id) 
                {
                    index_by_id_.erase(entity->id());
                    delete entity;
                }
                else 
                {
                    c.push_back(entity);
                }
            }
            cache_.clear();
            cache_.swap(c);
        }
        catch(const wxSQLite3Exception &e) 
        { 
            wxLogError("%s: Exception %%s", e.GetMessage().utf8_str());
            return false;
        }

        return true;
    }

    /** Remove the Data record from the database and the memory table (cache) */
    bool remove(Self::Data* entity, wxSQLite3Database* db)
    {
        if (remove(entity->id(), db))
        {
            entity->id(-1);
            return true;
        }

        return false;
    }
''' % (self._table, self._primay_key, self._table)

        s += '''
    template<typename... Args>
    Self::Data* get_one(const Args& ... args)
    {
        for (auto& [_, item] : index_by_id_)
        {
            if (item->id() > 0 && match(item, args...)) 
            {
                ++ hit_;
                return item;
            }
        }

        ++ miss_;

        return 0;
    }'''

        s += '''
    
    /**
    * Search the memory table (Cache) for the data record.
    * If not found in memory, search the database and update the cache.
    */
    Self::Data* get(const int64 id, wxSQLite3Database* db)
    {
        if (id <= 0) 
        {
            ++ skip_;
            return nullptr;
        }

        if (auto it = index_by_id_.find(id); it != index_by_id_.end())
        {
            ++ hit_;
            return it->second;
        }
        
        ++ miss_;
        Self::Data* entity = nullptr;
        wxString where = wxString::Format(" WHERE %s = ?", PRIMARY::name().utf8_str());
        try
        {
            wxSQLite3Statement stmt = db->PrepareStatement(this->query() + where);
            stmt.Bind(1, id);

            wxSQLite3ResultSet q = stmt.ExecuteQuery();
            if(q.NextRow())
            {
                entity = new Self::Data(q, this);
                cache_.push_back(entity);
                index_by_id_.insert(std::make_pair(id, entity));
            }
            stmt.Finalize();
        }
        catch(const wxSQLite3Exception &e) 
        { 
            wxLogError("%s: Exception %s", this->name().utf8_str(), e.GetMessage().utf8_str());
        }
        
        if (!entity) 
        {
            entity = this->fake_;
            // wxLogError("%s: %d not found", this->name().utf8_str(), id);
        }
 
        return entity;
    }
    /**
    * Search the database for the data record, bypassing the cache.
    */
    Self::Data* get_record(const int64 id, wxSQLite3Database* db)
    {
        if (id <= 0) 
        {
            ++ skip_;
            return nullptr;
        }

        Self::Data* entity = nullptr;
        wxString where = wxString::Format(" WHERE %s = ?", PRIMARY::name().utf8_str());
        try
        {
            wxSQLite3Statement stmt = db->PrepareStatement(this->query() + where);
            stmt.Bind(1, id);

            wxSQLite3ResultSet q = stmt.ExecuteQuery();
            if(q.NextRow())
            {
                entity = new Self::Data(q, this);
            }
            stmt.Finalize();
        }
        catch(const wxSQLite3Exception &e) 
        { 
            wxLogError("%s: Exception %s", this->name().utf8_str(), e.GetMessage().utf8_str());
        }
        
        if (!entity) 
        {
            entity = this->fake_;
            // wxLogError("%s: %d not found", this->name().utf8_str(), id);
        }
 
        return entity;
    }
'''
        s += '''
    /**
    * Return a list of Data records (Data_Set) derived directly from the database.
    * The Data_Set is sorted based on the column number.
    */
    const Data_Set all(wxSQLite3Database* db, const COLUMN col = COLUMN(0), const bool asc = true)
    {
        Data_Set result;
        try
        {
            wxSQLite3ResultSet q = db->ExecuteQuery(col == COLUMN(0) ? this->query() : this->query() + " ORDER BY " + column_to_name(col) + " COLLATE NOCASE " + (asc ? " ASC " : " DESC "));

            while(q.NextRow())
            {
                Self::Data entity(q, this);
                result.push_back(std::move(entity));
            }

            q.Finalize();
        }
        catch(const wxSQLite3Exception &e) 
        { 
            wxLogError("%s: Exception %s", this->name().utf8_str(), e.GetMessage().utf8_str());
        }

        return result;
    }
'''
        s += '''};

'''
        return s

def generate_base_class(header, fields=set):
    """Generate the base class"""
    code = header + '''#pragma once

#include <vector>
#include <map>
#include <random>
#include <algorithm>
#include <functional>
#include <cwchar>
#include <wx/wxsqlite3.h>
#include <wx/intl.h>

#include "rapidjson/document.h"
#include "rapidjson/pointer.h"
#include "rapidjson/prettywriter.h"
#include "rapidjson/stringbuffer.h"
using namespace rapidjson;

#include "html_template.h"
using namespace tmpl;

typedef wxLongLong int64;

class wxString;
enum OP { EQUAL = 0, GREATER, LESS, GREATER_OR_EQUAL, LESS_OR_EQUAL, NOT_EQUAL };

template<class V>
struct DB_Column
{
    V v_;
    OP op_;
    DB_Column(const V& v, OP op = EQUAL): v_(v), op_(op)
    {}
};

static int64 ticks_last_ = 0;
    
struct DB_Table
{
    DB_Table(): hit_(0), miss_(0), skip_(0) {};
    virtual ~DB_Table() {};
    wxString query_;
    size_t hit_, miss_, skip_;
    virtual wxString query() const { return this->query_; }
    virtual size_t num_columns() const = 0;
    virtual wxString name() const = 0;

    bool exists(wxSQLite3Database* db) const
    {
       return db->TableExists(this->name()); 
    }

    void drop(wxSQLite3Database* db) const
    {
        db->ExecuteUpdate("DROP TABLE IF EXISTS " + this->name());
    }

    static int64 newId()
    {
        // Get the current time in milliseconds as wxLongLong/int64
        int64 ticks = wxDateTime::UNow().GetValue();
        // Ensure uniqueness from last generated value
        if (ticks <= ticks_last_)
            ticks = ticks_last_ + 1;
        ticks_last_ = ticks;
        // Generate a random 3-digit number (0 to 999)
        std::random_device rd;
        std::mt19937 gen(rd());
        std::uniform_int_distribution<int> dist(0, 999);
        int randomSuffix = dist(gen);
        // Combine ticks and randomSuffix
        return (ticks * 1000) + randomSuffix;
    }
};

template<typename Arg1>
void condition(wxString& out, bool /*op_and*/, const Arg1& arg1)
{
    out += Arg1::name();
    switch (arg1.op_)
    {
    case GREATER:           out += " > ? ";     break;
    case GREATER_OR_EQUAL:  out += " >= ? ";    break;
    case LESS:              out += " < ? ";     break;
    case LESS_OR_EQUAL:     out += " <= ? ";    break;
    case NOT_EQUAL:         out += " != ? ";    break;
    default:
        out += " = ? "; break;
    }
}

template<typename Arg1, typename... Args>
void condition(wxString& out, bool op_and, const Arg1& arg1, const Args&... args) 
{
    out += Arg1::name();
    switch (arg1.op_)
    {
    case GREATER:           out += " > ? ";     break;
    case GREATER_OR_EQUAL:  out += " >= ? ";    break;
    case LESS:              out += " < ? ";     break;
    case LESS_OR_EQUAL:     out += " <= ? ";    break;
    case NOT_EQUAL:         out += " != ? ";    break;
    default:
        out += " = ? "; break;
    }
    out += op_and? " AND " : " OR ";
    condition(out, op_and, args...);
}

template<typename Arg1>
void bind(wxSQLite3Statement& stmt, int index, const Arg1& arg1)
{
    stmt.Bind(index, arg1.v_);
}

template<typename Arg1, typename... Args>
void bind(wxSQLite3Statement& stmt, int index, const Arg1& arg1, const Args&... args)
{
    stmt.Bind(index, arg1.v_); 
    bind(stmt, index+1, args...);
}

template<typename TABLE, typename... Args>
const typename TABLE::Data_Set find_by(TABLE* table, wxSQLite3Database* db, bool op_and, const Args&... args)
{
    typename TABLE::Data_Set result;
    try
    {
        wxString query = table->query() + " WHERE ";
        condition(query, op_and, args...);
        wxSQLite3Statement stmt = db->PrepareStatement(query);
        bind(stmt, 1, args...);

        wxSQLite3ResultSet q = stmt.ExecuteQuery();

        while(q.NextRow())
        {
            typename TABLE::Data entity(q, table);
            result.push_back(std::move(entity));
        }

        q.Finalize();
    }
    catch(const wxSQLite3Exception &e) 
    { 
        wxLogError("%s: Exception %s", table->name().utf8_str(), e.GetMessage().utf8_str());
    }
 
    return result;
}

template<class DATA, typename Arg1>
bool match(const DATA* data, const Arg1& arg1)
{
    return data->match(arg1);
}

template<class DATA, typename Arg1, typename... Args>
bool match(const DATA* data, const Arg1& arg1, const Args&... args)
{
    return (data->match(arg1) && ... && data->match(args));
}
'''
    for field in sorted(fields):
        if field == 'ACCOUNTNAME' or field == 'CATEGNAME' or field == 'PAYEENAME' or field == 'SUBCATEGNAME':
            code += '''
struct SorterBy%s
{ 
    template<class DATA>
    bool operator()(const DATA& x, const DATA& y)
    {
        return (std::wcscoll(x.%s.Lower().wc_str(),y.%s.Lower().wc_str()) < 0);  // Locale case-insensitive
    }
};
''' % ( field, field, field)
        else:
            transl = 'wxGetTranslation' if field == 'CURRENCYNAME' else ''
            code += '''
struct SorterBy%s
{ 
    template<class DATA>
    bool operator()(const DATA& x, const DATA& y)
    {
        return %s(x.%s) < %s(y.%s);
    }
};
''' % (field, transl, field, transl, field)

    rfp = open('DB_Table.h', 'w')
    rfp.write(code)
    rfp.close()

if __name__ == '__main__':
    header = '''// -*- C++ -*-
//=============================================================================
/**
 *      Copyright: (c) 2013 - %s Guan Lisheng (guanlisheng@gmail.com)
 *      Copyright: (c) 2017 - 2018 Stefano Giorgio (stef145g)
 *      Copyright: (c) 2022 Mark Whalley (mark@ipx.co.uk)
 *
 *      @file
 *
 *      @author [%s]
 *
 *      @brief
 *
 *      Revision History:
 *          AUTO GENERATED at %s.
 *          DO NOT EDIT!
 */
//=============================================================================
'''% (datetime.date.today().year, os.path.basename(__file__), str(datetime.datetime.now()))

    conn, cur, sql_file = None, None, None
    try:
        sql_file = sys.argv[1]
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
    except:
        print (__doc__)
        sys.exit(1)

    sql = ""
    sql_txt = '''-- NOTE:
-- This file has been AUTO GENERATED from database/tables_v1.sql
-- All translation identifers "_tr_" have been removed.
-- This file can be used to manually generate a database.

'''

    for line_bytes in open(sql_file, 'rb'):
        line = line_bytes.decode('utf-8)')
        sql = sql + line

        if line.find('_tr_') > 0: # Remove _tr_ identifyer for wxTRANSLATE
            line = line.replace('_tr_', '')

        sql_txt = sql_txt + line
    
    # Generate a table that does not contain translation code identifyer
    print ('Generate SQL file: %s that can generate a clean database.' % sql_tables_data_filename)
    file_data = codecs.open(sql_tables_data_filename, 'w', 'utf-8')
    file_data.write(sql_txt)
    file_data.close()

    cur.executescript(sql)

    all_fields = set()
    for table, sql in get_table_list(cur):
        fields = get_table_info(cur, table)
        index = get_index_list(cur, table)
        data = get_data_initializer_list(cur, table)
        table = DB_Table(table, fields, index, data)
        table.generate_class(header, sql)
        table.generate_unicode_currency_upgrade_patch()
        table.generate_currency_upgrade_patch()
        for field in fields:
            all_fields.add(field['name'])

    generate_base_class(header, all_fields)

    conn.close()
    print ('End of Run')
