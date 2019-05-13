#ifndef JSONWAX_PARSER_H
#define JSONWAX_PARSER_H

/* Original author: Nikolai S | https://github.com/doublejim
 *
 * You may use this file under the terms of any of these licenses:
 * GNU General Public License version 2.0       https://www.gnu.org/licenses/gpl-2.0.html
 * GNU General Public License version 3         https://www.gnu.org/licenses/gpl-3.0.html
 */

#include <QByteArray>
#include <QVariantList>
#include <QDebug>
#include "JsonWaxEditor.h"

namespace JsonWaxInternals {

class EscapedCharacter
{
public:
    enum Type {CODE_POINT, ESCAPED_CHARACTER};
    Type TYPE = ESCAPED_CHARACTER;
    int POS = 0;
    EscapedCharacter( Type type, int position)
        :TYPE(type), POS(position){}
};

class Parser
{
public:
    enum ErrorCode {OK, UNEXPECTED_CHARACTER, EXPECTED_BOOLEAN_OR_NULL, SUDDEN_END_OF_DOCUMENT, NOT_A_NUMBER,
                    CHARACTER_AFTER_END_OF_DOCUMENT, NOT_A_HEX_VALUE, EXPECTED_QUOTE_OR_END_BRACE,
                    INVALID_STRING, EXPECTED_COMMA_OR_END_BRACE, EXPECTED_COMMA_OR_END_SQUARE_BRACKET,
                    EXPECTED_STARTING_CURLY_OR_SQUARE_BRACKET};

    ErrorCode LAST_ERROR = OK;
    int LAST_ERROR_POS = -1;

    QString errorToString()
    {
        switch( LAST_ERROR)
        {
        case OK:                                        return "No errors occured.";
        case UNEXPECTED_CHARACTER:                      return "Unexpected character.";
        case EXPECTED_BOOLEAN_OR_NULL:                  return "Expected boolean or null.";
        case EXPECTED_COMMA_OR_END_BRACE:               return "Expected comma or closing curly bracket.";
        case EXPECTED_COMMA_OR_END_SQUARE_BRACKET:      return "Expected comma or closing square bracket.";
        case EXPECTED_STARTING_CURLY_OR_SQUARE_BRACKET: return "Expected opening curly or square bracket.";
        case SUDDEN_END_OF_DOCUMENT:                    return "Document ended unexpectedly.";
        case NOT_A_NUMBER:                              return "Not a number.";
        case CHARACTER_AFTER_END_OF_DOCUMENT:           return "Character after end of document.";
        case NOT_A_HEX_VALUE:                           return "Not a hexadecimal value.";
        case EXPECTED_QUOTE_OR_END_BRACE:               return "Expected quote or closing curly bracket.";
        case INVALID_STRING:                            return "Invalid string.";
        default:                                        return "";
        }
    }

    Parser(){}

private:
    Editor* EDITOR = 0;
    const QByteArray* BYTES;

    QVariantList KEYS;                                                          // [Editor]
    int POS_A, POSITION, SIZE;                                                  // [Editor]
    bool CONTAINS_ESCAPED_CHARACTERS = false;                                   // [Editor]
    bool NUMBER_CONTAINS_DOT_OR_E = false;                                      // [Editor]
    bool ERROR_REPORTED = false;
    QList<EscapedCharacter> ESCAPED_CHARACTERS;                                 // [Editor]

    QVariant A_B_asVariant(QMetaType::Type saveAsType)                          // [Editor]
    {
        QVariant result;
        int POS_B = POSITION;

        switch( saveAsType)
        {
        case QMetaType::QString:                                                // Get rid of quotes, and replace \uXXXX unicode
        {                                                                       // code points, and other escaped characters, with
            if (!CONTAINS_ESCAPED_CHARACTERS)                                   // the proper characters. The escaped characters
            {                                                                   // were detected during parsing.
                result = QString( BYTES->mid( POS_A, POS_B - POS_A - 1));       // The last character is a closing quotation mark.
            } else {
                QString str;
                QString codepointAsHex;
                int left = POS_A;

                for (EscapedCharacter ch : ESCAPED_CHARACTERS)
                {
                    switch(ch.TYPE)
                    {
                    case EscapedCharacter::Type::ESCAPED_CHARACTER:
                        str.append( BYTES->mid( left, ch.POS - left - 1));          // Until right before the back slash.
                        switch( BYTES->at( ch.POS))
                        {
                            case '\"':  str.append('\"');   break;
                            case '\\':  str.append('\\');   break;
                            case '/':   str.append('/');    break;
                            case 'b':   str.append('\b');   break;
                            case 'f':   str.append('\f');   break;
                            case 'n':   str.append('\n');   break;
                            case 'r':   str.append('\r');   break;
                            case 't':   str.append('\t');   break;
                            default: break; // Can't happen.
                        }
                        left = ch.POS + 1;
                        break;
                    case EscapedCharacter::Type::CODE_POINT:
                    {
                        str.append( BYTES->mid( left, ch.POS - left));
                        codepointAsHex = BYTES->mid( ch.POS + 2, 4);
                        int codepointAsInt = std::stoi (codepointAsHex.toStdString(), 0, 16);
                        str.append( QChar( codepointAsInt));
                        left = ch.POS + 6;
                        break;
                    }
                    default: break; // Can't happen.
                    }
                }
                str.append( BYTES->mid( left, POS_B - left - 1));                   // The last character is a closing quotation mark.
                result = str;
                CONTAINS_ESCAPED_CHARACTERS = false;
            }
            break;
        }
        case QMetaType::Int:                                                        // It's not actually stored as an Int.
        {                                                                           // The type of the number is determined here.
            QByteArray bytesResult (BYTES->mid( POS_A, POS_B - POS_A));

            if (NUMBER_CONTAINS_DOT_OR_E)
            {
                result = bytesResult.toDouble();
            } else if (bytesResult.size() > 9) {
                if (bytesResult.toLongLong() > 2147483647 || bytesResult.toLongLong() < -2147483647)
                    result = bytesResult.toLongLong();
                else
                    result = bytesResult.toInt();
            } else {
                result = bytesResult.toInt();
            }
            break;
        }
        case QMetaType::Bool:
            if (BYTES->at(POS_A) == 't')
                result = true;
            else
                result = false;
            break;
        default: break; // Empty QVariant.
        }
        return result;
    }

    void saveToEditor( const QVariant& value)                                          // [Editor]
    {
        EDITOR->setValue( KEYS, value);
    }

    bool error( ErrorCode code)
    {
        LAST_ERROR = code;
        LAST_ERROR_POS = POSITION;
        ERROR_REPORTED = true;
        return false;
    }

    bool checkHex(int length)
    {
        int iteration = 0;
        while ( POSITION < SIZE && iteration < length)
            switch (BYTES->at( POSITION++))
            {
            case '0': case '1': case '2': case '3': case '4': case '5': case '6': case '7': case '8': case '9':
            case 'a': case 'b': case 'c': case 'd': case 'e': case 'f':
            case 'A': case 'B': case 'C': case 'D': case 'E': case 'F':
                ++iteration;
                continue;
            default:
                return error( NOT_A_HEX_VALUE);
            }
        return true;
    }

    // ------------ START OF VERIFY NUMBER ------------

    bool number8()     // Acceptable position.
    {
        while (POSITION < SIZE)
        {
            switch (BYTES->at( POSITION++))
            {
            case '0': case '1': case '2': case '3': case '4': case '5': case '6': case '7': case '8': case '9':
                return number8();
            default:
                --POSITION;
                return true;
            }
        }
        return error( SUDDEN_END_OF_DOCUMENT);
    }

    bool number7()     // Acceptable position.
    {
        while (POSITION < SIZE)
        {
            switch (BYTES->at( POSITION++))
            {
            case '0': case '1': case '2': case '3': case '4': case '5': case '6': case '7': case '8': case '9':
                return number7();
            case 'e': case 'E':
                NUMBER_CONTAINS_DOT_OR_E = true;
                return number4();
            default:
                --POSITION;
                return true;
            }
        }
        return error( SUDDEN_END_OF_DOCUMENT);
    }

    bool number6()     // Acceptable position.
    {
        while (POSITION < SIZE)
        {
            switch (BYTES->at( POSITION++))
            {
            case '0': case '1': case '2': case '3': case '4': case '5': case '6': case '7': case '8': case '9':
                return number6();
            case '.':
                NUMBER_CONTAINS_DOT_OR_E = true;
                return number3();
            case 'e': case 'E':
                NUMBER_CONTAINS_DOT_OR_E = true;
                return number4();
            default:
                --POSITION;
                return true;
            }
        }
        return error( SUDDEN_END_OF_DOCUMENT);
    }

    bool number5()
    {
        while (POSITION < SIZE)
        {
            switch (BYTES->at( POSITION++))
            {
            case '0': case '1': case '2': case '3': case '4': case '5': case '6': case '7': case '8': case '9':
                return number8();
            default:
                --POSITION;
                return false;
            }
        }
        return error( SUDDEN_END_OF_DOCUMENT);
    }

    bool number4()
    {
        while (POSITION < SIZE)
        {
            switch (BYTES->at( POSITION++))
            {
            case '+': case '-':
                return number5();
            case '0': case '1': case '2': case '3': case '4': case '5': case '6': case '7': case '8': case '9':
                return number8();
            default:
                --POSITION;
                return false;
            }
        }
        return error( SUDDEN_END_OF_DOCUMENT);
    }

    bool number3()
    {
        while (POSITION < SIZE)
        {
            switch (BYTES->at( POSITION++))
            {
            case '0': case '1': case '2': case '3': case '4': case '5': case '6': case '7': case '8': case '9':
                return number7();
            default:
                --POSITION;
                return false;
            }
        }
        return error( SUDDEN_END_OF_DOCUMENT);
    }

    bool number2()      // Acceptable position.
    {
        while (POSITION < SIZE)
        {
            switch (BYTES->at( POSITION++))
            {
            case 'e': case 'E':
                NUMBER_CONTAINS_DOT_OR_E = true;
                return number4();
            case '.':
                NUMBER_CONTAINS_DOT_OR_E = true;
                return number3();
            default:
                --POSITION;
                return true;
            }
        }
        return error( SUDDEN_END_OF_DOCUMENT);
    }

    bool number1()
    {
        while (POSITION < SIZE)
        {
            switch (BYTES->at( POSITION++))
            {
            case '0':
                return number2();
            case '1': case '2': case '3': case '4': case '5': case '6': case '7': case '8': case '9':
                return number6();
            default:
                --POSITION;
                return false;
            }
        }
        return error( SUDDEN_END_OF_DOCUMENT);
    }

    bool verifyNumber()
    {
        NUMBER_CONTAINS_DOT_OR_E = false;

        while (POSITION < SIZE)
        {
            switch (BYTES->at( POSITION++))
            {
            case '-':
                if (!number1()) {
                    if (!ERROR_REPORTED)
                        return error( NOT_A_NUMBER);
                    return false;
                } else return true;
            case '0':
                if (!number2()) {
                    if (!ERROR_REPORTED)
                        return error( NOT_A_NUMBER);
                    return false;
                } else return true;
            case '1': case '2': case '3': case '4': case '5': case '6': case '7': case '8': case '9':
                if (!number6()) {
                    if (!ERROR_REPORTED)
                        return error( NOT_A_NUMBER);
                    return false;
                } else return true;
            default:
                --POSITION;
                return error( NOT_A_NUMBER);
            }
        }
        return error( SUDDEN_END_OF_DOCUMENT);
    }
    // ------------ END OF VERIFY NUMBER ------------

    void skipSpace()
    {
        while ( POSITION < SIZE )
            if (BYTES->at( POSITION) == ' ' || BYTES->at( POSITION) == '\n' || BYTES->at( POSITION) == '\r' || BYTES->at( POSITION) == '\t')
            {
                ++POSITION;
                continue;
            } else {
                return;
            }
    }

    bool expectChar( QChar character)
    {
        skipSpace();
        while ( POSITION < SIZE )
        {
            if (BYTES->at( POSITION++) == character)
                return true;
            else
                return error( UNEXPECTED_CHARACTER);
        }
        return error( SUDDEN_END_OF_DOCUMENT);
    }

    bool expectExactStr( QString toExpect) // Except from the first character in the toExpect-string.
    {
        int matchPos = 1;

        while ( POSITION < SIZE )
        {
            if (BYTES->at( POSITION++) == toExpect.at( matchPos))
            {
                if (++matchPos > toExpect.length() - 1)
                    return true;
                continue;
            } else {
                return error( EXPECTED_BOOLEAN_OR_NULL);
            }
        }
        return error( SUDDEN_END_OF_DOCUMENT);
    }

    bool verifyInnerObject()
    {
    inner_begin:
        POS_A = POSITION;                                               // For combining Parser with Editor.

        if (verifyString())
        {
            KEYS.append( A_B_asVariant(QMetaType::QString));            // For combining Parser with Editor.

            if (expectChar(':'))
            {
                if (verifyValue())
                {
                    skipSpace();
                    while ( POSITION < SIZE )
                    {
                        switch ( BYTES->at( POSITION++))
                        {
                        case '}':
                            KEYS.removeLast();                          // For combining Parser with Editor.
                            return true;
                        case ',':
                            KEYS.removeLast();                          // For combining Parser with Editor.
                            if (expectChar('\"'))
                                goto inner_begin;
                            return false;
                        default:
                            return error( EXPECTED_COMMA_OR_END_BRACE);
                        }
                    }
                    return error( SUDDEN_END_OF_DOCUMENT);
                }
            }
        }
        return false;
    }

    bool verifyObject()
    {
        while ( POSITION < SIZE )
        {
            skipSpace();
            if (POSITION < SIZE)
            {
                switch (BYTES->at( POSITION))
                {
                case '\"':
                    ++POSITION;
                    return verifyInnerObject();
                case '}':
                    ++POSITION;
                    EDITOR->setEmptyObject( KEYS);                      // For combining Parser with Editor (save empty object).
                    return true;
                default:
                    return error( EXPECTED_QUOTE_OR_END_BRACE);
                }
            } else {
                return error( SUDDEN_END_OF_DOCUMENT);
            }
        }
        return error( SUDDEN_END_OF_DOCUMENT);
    }

    bool verifyInnerArray()
    {
        int elementPosition = 0;
    inner_begin:
        skipSpace();
        POS_A = POSITION;                                               // For combining Parser with Editor.
        KEYS.append( elementPosition);                                  // For combining Parser with Editor.
        if (verifyValue())
        {
            KEYS.removeLast();                                          // For combining Parser with Editor.

            skipSpace();
            while ( POSITION < SIZE )
            {
                switch( BYTES->at( POSITION))
                {
                case ',':
                    ++POSITION;
                    ++elementPosition;
                    goto inner_begin;
                case ']':                                               // There's only one way to end the array: with a ]
                    ++POSITION;
                    return true;
                default:
                    return error( EXPECTED_COMMA_OR_END_SQUARE_BRACKET);
                }
            }
            return error( SUDDEN_END_OF_DOCUMENT);
        } else {
            return false;                                               // The error was already reported.
        }
    }

    bool verifyArray()
    {
        skipSpace();
        while ( POSITION < SIZE )
        {
            switch( BYTES->at( POSITION))
            {
            case ']':
                EDITOR->setEmptyArray( KEYS);                          // For combining Parser with Editor (save empty array).
                ++POSITION;
                return true;
            default:
                return verifyInnerArray();
            }
        }
        return error( SUDDEN_END_OF_DOCUMENT);
    }

    bool verifyString()
    {
        ESCAPED_CHARACTERS.clear();                                     // For combining Parser with Editor.
        CONTAINS_ESCAPED_CHARACTERS = false;                            // For combining Parser with Editor.

        while ( POSITION < SIZE )
        {
            switch ( BYTES->at( POSITION++))                            // The loop is looking for backspace or "
            {
            case '\\':
                switch ( BYTES->at( POSITION++))                        // Inner test.
                {
                case '\"': case '\\': case '/': case 'b': case 'f': case 'n': case 'r': case 't':
                    ESCAPED_CHARACTERS.append( EscapedCharacter( EscapedCharacter::Type::ESCAPED_CHARACTER, POSITION - 1));
                    CONTAINS_ESCAPED_CHARACTERS = true;
                    break;                                              // Go to next character.
                case 'u':
                    if (checkHex(4))
                    {
                        ESCAPED_CHARACTERS.append( EscapedCharacter( EscapedCharacter::Type::CODE_POINT, POSITION - 6));
                        CONTAINS_ESCAPED_CHARACTERS = true;             // A valid code point always has the same length.
                        --POSITION;
                        break;                                          // Get out of inner, go to next character.
                    } else {
                        --POSITION;
                        return error( NOT_A_HEX_VALUE);
                    }
                default:
                    return error( INVALID_STRING);
                }
                break;
            case '\"':
                return true;                                            // End of string.
            }
        }
        return error( SUDDEN_END_OF_DOCUMENT);
    }

    bool verifyValue()
    {
        skipSpace();
        POS_A = POSITION;                                               // [Editor]
        while ( POSITION < SIZE )
        {
            switch ( BYTES->at( POSITION++))
            {
            case '{':
                return verifyObject();
            case '[':
                return verifyArray();
            case '\"':
            {
                ++POS_A;                                                // Skip the opening quotation mark. [Editor]
                bool result = verifyString();
                if (result)
                    saveToEditor( A_B_asVariant( QMetaType::QString));  // [Editor]
                return result;
            }
            case '-': case '0': case '1': case '2': case '3': case '4': case '5': case '6': case '7': case '8': case '9':
            {
                --POSITION;
                bool result = verifyNumber();
                if (result)
                    saveToEditor( A_B_asVariant( QMetaType::Int));      // [Editor]
                return result;
            }
            case 't':
            {
                bool result = expectExactStr("true");
                if (result)
                    saveToEditor( A_B_asVariant( QMetaType::Bool));     // [Editor]
                return result;
            }
            case 'f':
            {
                bool result = expectExactStr("false");
                if (result)
                    saveToEditor( A_B_asVariant( QMetaType::Bool));     // [Editor]
                return result;
            }
            case 'n':
            {
                bool result = expectExactStr("null");
                if (result)
                    saveToEditor( A_B_asVariant( QMetaType::Void));     // [Editor]
                return result;
            }
            default:
                qDebug() << "Warning from JSON wax: Unexpected character at position" << POSITION << "- total file size is" << SIZE;
                return error( UNEXPECTED_CHARACTER);
            }
        }
        return error( SUDDEN_END_OF_DOCUMENT);
    }

public:
    Editor* getEditorObject()
    {
        return EDITOR;
    }

    bool isWellformed( const QByteArray& bytes)
    {
        POSITION = 0;
        BYTES = &bytes;
        SIZE = bytes.size();

        EDITOR = new Editor();                                          // The editor is deleted in JsonWax.h
        KEYS.clear();                                                   // [Editor]

        while (POSITION < SIZE)
        {
            skipSpace();
            switch( bytes.at( POSITION++))
            {
            case '{':
                if (!verifyObject())
                    return false;
                break;
            case '[':
                if (!verifyArray())
                    return false;
                break;
            default:
                return error( EXPECTED_STARTING_CURLY_OR_SQUARE_BRACKET);
            }

            skipSpace();
            if (POSITION < SIZE)
            {
                return error( CHARACTER_AFTER_END_OF_DOCUMENT);
            }
                LAST_ERROR_POS = -1;
                LAST_ERROR = OK;
                return true;                                            // We are at the end of the document,
                                                                        // and the object or array was valid.
        }
        return error( SUDDEN_END_OF_DOCUMENT);
    }
};
}

#endif // JSONWAX_PARSER_H
